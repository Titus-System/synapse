"""A taxa nova em até três tentativas, do resultado do worker à proposta seguinte (T-271).

Consumer, roteador, entrypoint e nós são os reais, e cada publicação é conferida contra o
schema oficial (`ConfirmacaoFalsa`). O banco é o `HistoricoFalso`; o teste faz a api, que grava
a versão de cada proposta e reabre o ciclo por `regra-submetida`, e o worker, que grava e
publica o resultado de cada simulação.
"""

import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import simplejson
from httpx import AsyncClient
from jsonschema import Draft202012Validator, FormatChecker
from prometheus_client.parser import text_string_to_metric_families

from app.contratos.mensagens import RegraSubmetida, SimulacaoConcluida
from app.core.logger import FormatadorJson, ManipuladorFilaContexto
from app.mensageria.consumers import Consumer
from tests.app.confirmacao_falsa import ConfirmacaoFalsa, mensagem
from tests.app.iteracao_falsa import NUCLEO, HistoricoFalso
from tests.app.test_mensageria import CONTRATOS, exemplo

ORCAMENTO = Decimal("1700")
# A comissão da loja que a regra não alcança, que o detalhamento de cada resultado traz.
PARTE_FIXA = Decimal("1000")
# A comissão que o worker apura para a original (0,03) e para cada alternativa. A estimativa
# inicial e as duas refinadas são 0,0175, 0,0143 e 0,0086, e nenhuma cabe em 1700.
COMISSOES_QUE_NAO_CABEM = (Decimal("2200"), Decimal("1800"), Decimal("1764"), Decimal("1710"))


class Job:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        com_orcamento: bool = True,
        orcamento: Decimal = ORCAMENTO,
    ) -> None:
        self.ambiente = ConfirmacaoFalsa(monkeypatch)
        self.orcamento = orcamento
        self.historico = HistoricoFalso(uuid4(), orcamento, PARTE_FIXA)
        self.historico.instalar(monkeypatch)
        self.com_orcamento = com_orcamento
        self.submissao = Consumer(RegraSubmetida, "regra-submetida", self.ambiente.roteador)
        self.resultado = Consumer(SimulacaoConcluida, "simulacao-concluida", self.ambiente.roteador)

    def original(self, especificacoes: list[Any] | None = None) -> UUID:
        return self.historico.gravar_versao(
            {"nucleo": dict(NUCLEO), "especificacoes": especificacoes or []}, "extracao"
        )

    async def abrir_ciclo(self, regra_id: UUID) -> None:
        """O `regra-submetida` que a api publica ao gravar a versão, com os parâmetros do job."""
        payload = exemplo("regra-submetida-parametros") | {
            "job_id": str(self.historico.job_id),
            "regra_id": str(regra_id),
            "orcamento": self.orcamento,
        }
        if not self.com_orcamento:
            del payload["orcamento"]
        recebida = mensagem(payload)

        await self.submissao.receber(recebida)

        recebida.ack.assert_awaited_once_with()

    def resultado_do_worker(self, regra_id: UUID, simulado: Decimal) -> dict[str, Any]:
        resultado_id = self.historico.gravar_resultado(regra_id, simulado)
        if not self.com_orcamento:
            base = exemplo("simulacao-concluida-sem-orcamento")
        else:
            veredito = "inviavel" if simulado > self.orcamento else "viavel"
            base = exemplo("simulacao-concluida") | {"veredito": veredito}
        return base | {"job_id": str(self.historico.job_id), "resultado_id": str(resultado_id)}

    async def entregar(self, payload: dict[str, Any]) -> Any:
        recebida = mensagem(payload)
        await self.resultado.receber(recebida)
        return recebida

    async def simular(self, regra_id: UUID, simulado: Decimal) -> dict[str, Any]:
        payload = self.resultado_do_worker(regra_id, simulado)
        recebida = await self.entregar(payload)
        recebida.ack.assert_awaited_once_with()
        return payload

    async def alternativa(self, proposta: dict[str, Any]) -> UUID:
        """A api grava a proposta como versão nova e reabre o ciclo dela."""
        regra_id = self.historico.gravar_proposta(proposta)
        await self.abrir_ciclo(regra_id)
        return regra_id

    def publicadas(self, evento: str) -> list[dict[str, Any]]:
        return [payload for nome, payload in self.ambiente.publicacoes if nome == evento]

    def propostas(self) -> list[dict[str, Any]]:
        return self.publicadas("sugestao-adaptacao-proposta")

    def etapas(self, status: str) -> list[dict[str, Any]]:
        return [p for p in self.publicadas("etapa-alterada") if p["status"] == status]


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


def amostra(texto: str, tentativa: str, desfecho: str) -> float:
    return next(
        (
            a.value
            for f in text_string_to_metric_families(texto)
            for a in f.samples
            if a.name == "codegen_sugestao_adaptacao_tentativas_total"
            and a.labels == {"tentativa": tentativa, "desfecho": desfecho}
        ),
        0.0,
    )


def percentual(proposta: dict[str, Any]) -> Decimal:
    valor: Decimal = proposta["representacao"]["nucleo"]["percentual"]
    return valor


def taxas_por_cargo(proposta: dict[str, Any]) -> dict[str, Decimal]:
    return {
        par["cargo"]: par["percentual"]
        for par in proposta["representacao"]["nucleo"]["taxas_por_cargo"]
    }


async def test_tres_taxas_que_nao_cabem_encerram_a_iteracao_sem_alternativa(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    job = Job(monkeypatch)
    regra = job.original()
    await job.abrir_ciclo(regra)
    antes = (await cliente.get("/metrics")).text
    origem, *simuladas = COMISSOES_QUE_NAO_CABEM

    versoes_simuladas = [regra]
    await job.simular(regra, origem)
    for comissao in simuladas:
        alternativa = await job.alternativa(job.propostas()[-1])
        versoes_simuladas.append(alternativa)
        await job.simular(alternativa, comissao)

    propostas = job.propostas()
    assert [p["tentativa"] for p in propostas] == [1, 2, 3]
    assert [percentual(p) for p in propostas] == [
        Decimal("0.0175"),
        Decimal("0.0143"),
        Decimal("0.0086"),
    ]
    # Cada proposta adapta a versão que acabou de não caber.
    assert [UUID(p["regra_origem_id"]) for p in propostas] == versoes_simuladas[:3]
    assert job.etapas("sem_alternativa") == [
        {
            "job_id": str(job.historico.job_id),
            "etapa": "sugestao_adaptacao",
            "status": "sem_alternativa",
        }
    ]
    assert job.etapas("erro") == []
    depois = (await cliente.get("/metrics")).text
    for tentativa in ("1", "2", "3"):
        assert amostra(depois, tentativa, "inviavel") - amostra(antes, tentativa, "inviavel") == 1
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    for log in logs:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(log)
        assert log["job_id"] == str(job.historico.job_id)
    # Só o que o código escreve: o horário e os ids do envelope trazem dígitos ao acaso.
    escritos = simplejson.dumps([(log["message"], log.get("extra")) for log in logs])
    for valor in ("0.0175", "0.0143", "0.0086", "1764", "1710"):
        assert valor not in escritos


async def test_a_alternativa_que_coube_encerra_a_iteracao_sem_nova_proposta(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient
) -> None:
    job = Job(monkeypatch)
    regra = job.original()
    await job.abrir_ciclo(regra)
    await job.simular(regra, Decimal("2200"))
    alternativa = await job.alternativa(job.propostas()[0])
    antes = (await cliente.get("/metrics")).text

    await job.simular(alternativa, Decimal("1650"))

    assert len(job.propostas()) == 1
    assert job.etapas("sem_alternativa") == []
    estado = await job.ambiente.estado(
        {"job_id": str(job.historico.job_id), "regra_id": str(alternativa)}
    )
    assert estado.next == ()
    assert estado.values["encaminhamento"] == "fim"
    depois = (await cliente.get("/metrics")).text
    assert amostra(depois, "1", "viavel") - amostra(antes, "1", "viavel") == 1


async def test_com_comissao_atual_no_escopo_a_primeira_taxa_e_a_que_cabe_e_encerra_a_iteracao(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    """A regra troca 2% por 3% nas vendas de R$ 40.000 da loja 13, e a loja fora dela fica com
    R$ 1.000: a comissão é 1000 + 40000 * taxa. Em R$ 2.000 cabe até 2,5%, e é essa a primeira
    taxa, que a simulação confirma. Pelo baseline inteiro (R$ 1.800), ela seria 1,5%, abaixo dos
    2% que a loja já recebe, e caberia do mesmo jeito: seria a sugestão final."""
    job = Job(monkeypatch, orcamento=Decimal("2000"))
    regra = job.original()
    await job.abrir_ciclo(regra)
    await job.simular(regra, Decimal("2200"))
    alternativa = await job.alternativa(job.propostas()[0])

    await job.simular(alternativa, Decimal("2000"))

    [proposta] = job.propostas()
    assert percentual(proposta) == Decimal("0.025")
    assert job.etapas("sem_alternativa") == []
    [publicada] = [log for log in logs if log["message"] == "adaptation proposal published"]
    assert publicada["extra"]["metodo"] == "estimativa"


async def test_regra_nova_no_job_depois_de_uma_iteracao_comeca_pela_estimativa_dos_totais(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A conta das tentativas é do job, mas a regra nova não tem taxas simuladas a refinar."""
    job = Job(monkeypatch)
    regra = job.original()
    await job.abrir_ciclo(regra)
    await job.simular(regra, Decimal("2200"))
    alternativa = await job.alternativa(job.propostas()[0])
    await job.simular(alternativa, Decimal("1650"))
    nova = job.historico.gravar_versao(
        {"nucleo": {**NUCLEO, "loja": ["14"]}, "especificacoes": []}, "correcao", alternativa
    )
    await job.abrir_ciclo(nova)

    await job.simular(nova, Decimal("2200"))

    _, proposta = job.propostas()
    assert proposta["tentativa"] == 2
    assert proposta["regra_origem_id"] == str(nova)
    assert percentual(proposta) == Decimal("0.0175")
    assert job.etapas("sem_alternativa") == []


async def test_regra_com_taxas_por_cargo_e_elemento_generico_e_adaptada_e_refinada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As taxas caem na mesma proporção que a do cargo 100, a referência, que segue a reta das
    outras iterações: 0,0175 pela estimativa e 0,0143 pelo refinamento. O elemento genérico
    segue como estava."""
    job = Job(monkeypatch)
    generico = simplejson.loads(
        (CONTRATOS / "examples/domain/representacao-regra-generico.json").read_bytes(),
        use_decimal=True,
    )["especificacoes"]
    nucleo = {chave: valor for chave, valor in NUCLEO.items() if chave != "percentual"}
    regra = job.historico.gravar_versao(
        {
            "nucleo": {
                **nucleo,
                "cargo": ["100", "150"],
                "taxas_por_cargo": [
                    {"cargo": "100", "percentual": Decimal("0.03")},
                    {"cargo": "150", "percentual": Decimal("0.05")},
                ],
            },
            "especificacoes": generico,
        },
        "extracao",
    )
    await job.abrir_ciclo(regra)

    await job.simular(regra, Decimal("2200"))
    alternativa = await job.alternativa(job.propostas()[0])
    await job.simular(alternativa, Decimal("1800"))

    primeira, segunda = job.propostas()
    assert [p["tentativa"] for p in (primeira, segunda)] == [1, 2]
    assert taxas_por_cargo(primeira) == {"100": Decimal("0.0175"), "150": Decimal("0.0291")}
    assert taxas_por_cargo(segunda) == {"100": Decimal("0.0143"), "150": Decimal("0.0237")}
    assert segunda["regra_origem_id"] == str(alternativa)
    assert primeira["representacao"]["especificacoes"] == generico
    assert segunda["representacao"]["especificacoes"] == generico
    assert job.etapas("sem_alternativa") == []
    assert job.etapas("erro") == []


async def test_job_sem_orcamento_nao_recebe_proposta(monkeypatch: pytest.MonkeyPatch) -> None:
    job = Job(monkeypatch, com_orcamento=False)
    regra = job.original()
    await job.abrir_ciclo(regra)

    await job.simular(regra, Decimal("2200"))

    assert job.propostas() == []
    assert job.etapas("sem_alternativa") == []
    assert job.etapas("erro") == []


async def test_reentrega_do_resultado_ja_processado_nao_publica_nada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job(monkeypatch)
    regra = job.original()
    await job.abrir_ciclo(regra)
    resultado = await job.simular(regra, Decimal("2200"))
    publicadas = list(job.ambiente.publicacoes)

    repetida = await job.entregar(resultado)

    repetida.ack.assert_awaited_once_with()
    assert job.ambiente.publicacoes == publicadas


async def test_reentrega_depois_de_a_api_gravar_a_proposta_repete_a_mesma_tentativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A trilha da sugestão falhou depois da proposta, que a api já gravou como versão nova.

    A reentrega refaz só a sugestão: ela não pode contar a versão nova como mais uma tentativa
    nem refinar com outra taxa, e repete a proposta que a api reconhece pelo hash.
    """
    job = Job(monkeypatch)
    regra = job.original()
    await job.abrir_ciclo(regra)
    await job.simular(regra, Decimal("2200"))
    primeira = await job.alternativa(job.propostas()[0])
    publicar = job.ambiente.producers.no_concluido.side_effect
    falhou = False

    async def falhar_na_trilha_da_sugestao(dto: Any) -> None:
        nonlocal falhou
        if dto.no == "sugestao_adaptacao" and not falhou:
            falhou = True
            raise RuntimeError("broker fora")
        await publicar(dto)

    job.ambiente.producers.no_concluido.side_effect = falhar_na_trilha_da_sugestao
    resultado = job.resultado_do_worker(primeira, Decimal("1800"))
    interrompida = await job.entregar(resultado)
    interrompida.nack.assert_awaited_once_with(requeue=True)
    job.historico.gravar_proposta(job.propostas()[-1])

    repetida = await job.entregar(resultado)

    repetida.ack.assert_awaited_once_with()
    _, segunda, repeticao = job.propostas()
    assert segunda == repeticao
    assert segunda["tentativa"] == 2
    assert job.etapas("sem_alternativa") == []


async def test_parte_fixa_acima_do_orcamento_simula_uma_alternativa_e_encerra_sem_outra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nenhuma taxa cabe em 900 com 1000 fora da regra. A alternativa da sondagem ainda é
    simulada, para o usuário vê-la, e a reta que passa por ela cruza o orçamento abaixo de zero."""
    job = Job(monkeypatch, orcamento=Decimal("900"))
    original = job.original()
    await job.abrir_ciclo(original)

    await job.simular(original, Decimal("2200"))
    (proposta,) = job.propostas()
    assert proposta["representacao"]["nucleo"]["percentual"] == Decimal("0.0122")
    alternativa = await job.alternativa(proposta)
    await job.simular(alternativa, Decimal("1500"))

    assert len(job.propostas()) == 1
    assert len(job.etapas("sem_alternativa")) == 1
