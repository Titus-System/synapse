"""A correção do código que falha na execução, do resultado do worker ao código corrigido.

Consumer, roteador, entrypoint e nós são os reais, e cada publicação é conferida contra o schema
oficial (`ConfirmacaoFalsa`). O teste faz a api, que abre o ciclo de cada versão, e o worker, que
grava e publica o resultado de cada código. A posição de cada código sai dos `no-concluido` da
geração publicados e a falha, do que o worker falso gravou; as consultas reais estão em
`tests/app/repositorio/test_correcao_postgres.py`.
"""

import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
import simplejson
from prometheus_client import REGISTRY

from app.core.logger import FormatadorJson, ManipuladorFilaContexto
from app.correcao_codigo import FalhaDaExecucao
from tests.app.graph.test_iteracao_da_taxa_nova import Job

MENSAGEM = "Series.duplicated() got an unexpected keyword argument 'subset'"
EXCECAO = {
    "causa": "excecao",
    "falha": {"tipo": "TypeError", "mensagem": MENSAGEM, "traceback": "line 64"},
}
NAO_FINITO = [
    {"nome": "sem_comissao_negativa", "detalhe": "valor não finito", "resultado": "violada"}
]


class Worker:
    """As falhas que o worker gravou, e a regra de cada código, como o banco as daria."""

    def __init__(self, job: Job, monkeypatch: pytest.MonkeyPatch) -> None:
        self.job = job
        self.falhas: dict[UUID, FalhaDaExecucao] = {}
        self.regras_das_falhas: dict[UUID, UUID] = {}
        monkeypatch.setattr("app.graph.nodes.decision.posicao_do_codigo", self.posicao)
        monkeypatch.setattr("app.graph.nodes.decision.buscar_falha_da_execucao", self.falha)
        monkeypatch.setattr("app.graph.nodes.code_generation.buscar_falha_da_execucao", self.falha)
        monkeypatch.setattr(
            "app.mensageria.roteamento.buscar_regra_do_resultado", self.regra_do_resultado
        )

    def codigos(self) -> list[tuple[str, str]]:
        """`(regra_id, codigo_gerado_id)` de cada código gerado, na ordem de gravação."""
        return [
            (p["regra_id"], p["codigo_gerado_id"])
            for p in self.job.publicadas("no-concluido")
            if p["no"] == "geracao_codigo"
        ]

    async def posicao(self, sessoes: Any, job_id: UUID, codigo_gerado_id: UUID) -> int:
        codigos = self.codigos()
        [regra] = [r for r, c in codigos if c == str(codigo_gerado_id)]
        da_versao = [c for r, c in codigos if r == regra]
        return da_versao.index(str(codigo_gerado_id)) + 1

    async def falha(self, sessoes: Any, job_id: UUID, resultado_id: UUID) -> FalhaDaExecucao:
        return self.falhas[resultado_id]

    async def regra_do_resultado(self, sessoes: Any, job_id: UUID, resultado_id: UUID) -> UUID:
        if resultado_id in self.regras_das_falhas:
            return self.regras_das_falhas[resultado_id]
        return await self.job.historico.buscar_regra_do_resultado(sessoes, job_id, resultado_id)

    async def falhar(
        self,
        regra_id: UUID,
        status: str = "erro_codigo",
        *,
        diagnostico: dict[str, Any] | None = None,
        assercoes: list[dict[str, Any]] | None = None,
    ) -> None:
        resultado_id = UUID(int=len(self.falhas) + 1)
        self.regras_das_falhas[resultado_id] = regra_id
        self.falhas[resultado_id] = FalhaDaExecucao(
            status,
            diagnostico if diagnostico is not None else EXCECAO,
            [a for a in assercoes or [] if a["resultado"] == "violada"],
        )
        recebida = await self.job.entregar(
            {
                "job_id": str(self.job.historico.job_id),
                "resultado_id": str(resultado_id),
                "status": status,
            }
        )
        recebida.ack.assert_awaited_once_with()


def _amostras(familia: str, rotulos: tuple[str, str]) -> dict[tuple[str, str], float]:
    return {
        (amostra.labels[rotulos[0]], amostra.labels[rotulos[1]]): amostra.value
        for coletada in REGISTRY.collect()
        if coletada.name == familia
        for amostra in coletada.samples
        if amostra.name.endswith("_total")
    }


def _variacao(
    familia: str, rotulos: tuple[str, str], antes: dict[tuple[str, str], float]
) -> dict[tuple[str, str], float]:
    depois = _amostras(familia, rotulos)
    return {k: depois[k] - antes.get(k, 0.0) for k in depois if depois[k] != antes.get(k, 0.0)}


PEDIDOS = ("codegen_correcoes_codigo", ("tentativa", "causa"))
DESFECHOS = ("codegen_correcao_codigo_desfechos", ("tentativa", "desfecho"))


@pytest.fixture
def logs() -> Iterator[list[dict[str, Any]]]:
    envelopes: list[dict[str, Any]] = []

    class Captura(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            preparado = ManipuladorFilaContexto(None).prepare(record)
            envelopes.append(simplejson.loads(FormatadorJson().format(preparado)))

    logger = logging.getLogger("app")
    handler = Captura()
    nivel = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield envelopes
    finally:
        logger.removeHandler(handler)
        logger.setLevel(nivel)


def _encaminhamentos(job: Job) -> list[str]:
    return [
        p["conclusao"]["encaminhamento"]
        for p in job.publicadas("no-concluido")
        if p["no"] == "decisao"
    ]


async def test_codigo_que_falha_volta_ao_modelo_e_o_corrigido_segue_para_a_decisao(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    job = Job(monkeypatch)
    worker = Worker(job, monkeypatch)
    regra = job.original()
    pedidos, desfechos = _amostras(*PEDIDOS), _amostras(*DESFECHOS)
    await job.abrir_ciclo(regra)

    await worker.falhar(regra)

    [primeiro, corrigido] = [c for _, c in worker.codigos()]
    assert primeiro != corrigido
    comandos = job.publicadas("executar-codigo")
    assert [c["codigo_gerado_id"] for c in comandos] == [primeiro, corrigido]
    [_, prompt_da_correcao] = job.ambiente.modelo.seen_messages
    correcao = simplejson.loads(prompt_da_correcao[0].content)
    assert correcao["dados_nao_confiaveis_da_execucao_anterior"] == {
        "codigo": "def aplicar_regra(bases, apuracao_base, competencias):\n    return {}\n",
        "falha": {"status": "erro_codigo", "causa": "excecao", "falha": EXCECAO["falha"]},
    }

    await job.simular(regra, Decimal("1500"))

    assert _encaminhamentos(job) == ["correcao_codigo", "fim"]
    assert len(job.publicadas("executar-codigo")) == 2
    assert _variacao(*PEDIDOS, pedidos) == {("2", "excecao"): 1.0}
    assert _variacao(*DESFECHOS, desfechos) == {("2", "sucesso"): 1.0}
    assert MENSAGEM not in simplejson.dumps(logs)
    [pedido] = [
        log
        for log in logs
        if log["message"] == "node conclusion published"
        and log.get("extra", {}).get("encaminhamento") == "correcao_codigo"
    ]
    assert pedido["extra"]["causa"] == "excecao"
    assert pedido["extra"]["posicao_do_codigo"] == 1


async def test_terceiro_codigo_que_falha_encerra_sem_nova_geracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job(monkeypatch)
    worker = Worker(job, monkeypatch)
    regra = job.original()
    pedidos, desfechos = _amostras(*PEDIDOS), _amostras(*DESFECHOS)
    await job.abrir_ciclo(regra)

    await worker.falhar(regra)
    await worker.falhar(regra, "assercao_violada", diagnostico={}, assercoes=NAO_FINITO)
    await worker.falhar(regra, diagnostico={"causa": "cobertura_incompleta"})

    assert len(job.publicadas("executar-codigo")) == 3
    assert len(job.ambiente.modelo.seen_messages) == 3
    assert _encaminhamentos(job) == ["correcao_codigo", "correcao_codigo", "fim"]
    assert _variacao(*PEDIDOS, pedidos) == {
        ("2", "excecao"): 1.0,
        ("3", "assercao_violada"): 1.0,
    }
    assert _variacao(*DESFECHOS, desfechos) == {("2", "erro"): 1.0, ("3", "erro"): 1.0}


async def test_alternativa_da_taxa_nova_que_falha_e_corrigida_e_a_iteracao_continua(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cada versão tem o próprio limite, e a correção não conta como tentativa de taxa."""
    job = Job(monkeypatch)
    worker = Worker(job, monkeypatch)
    original = job.original()
    await job.abrir_ciclo(original)
    await job.simular(original, Decimal("2200"))
    [proposta] = job.propostas()
    alternativa = await job.alternativa(proposta)

    await worker.falhar(alternativa)
    await job.simular(alternativa, Decimal("1800"))

    assert [p["tentativa"] for p in job.propostas()] == [1, 2]
    assert [r for r, _ in worker.codigos()] == [
        str(original),
        str(alternativa),
        str(alternativa),
    ]
