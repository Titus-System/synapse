"""A explicação do resultado no grafo, do `simulacao-concluida` à sugestão seguinte (T-317).

Consumer, roteador, entrypoint e nós são os reais, e cada publicação é conferida contra o schema
oficial (`ConfirmacaoFalsa`). O banco é o `HistoricoFalso` mais `ExplicacoesFalsas`, que guarda o
que o nó grava em `explicacoes` e o devolve na reexecução; o modelo é o `FakeChatModel`.
"""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
import simplejson
from httpx import AsyncClient
from jsonschema import Draft202012Validator, FormatChecker
from langchain_core.messages import AIMessage
from prometheus_client.parser import text_string_to_metric_families

from app.explicacao import formatar_reais
from app.graph.nodes import explain_result as modulo
from app.repositorio.artefatos import id_da_explicacao, id_do_prompt
from app.repositorio.explicacoes import ExplicacaoGravada
from tests.app.graph.conftest import FakeChatModel
from tests.app.graph.test_correcao_do_codigo import Worker
from tests.app.graph.test_iteracao_da_taxa_nova import Job, logs  # noqa: F401
from tests.app.iteracao_falsa import LOJA_FORA_DA_REGRA
from tests.app.test_mensageria import CONTRATOS

pytestmark = pytest.mark.com_explicacao

BASELINE = Decimal("1800")
SIMULADO = Decimal("2200")
DIFERENCA = SIMULADO - BASELINE
# Cada número como a lista do prompt o mostra: a narrativa que só cita esses é conferida.
NARRATIVA_CONFERIDA = (
    f"A regra simulou {formatar_reais(SIMULADO)} contra {formatar_reais(BASELINE)} do "
    f"baseline, uma diferença de {formatar_reais(DIFERENCA)}. A loja 13 concentrou o efeito."
)
# A participação da loja 13 na diferença é uma conta que o modelo fez, e ninguém apurou.
NARRATIVA_REPROVADA = "A loja 13 respondeu por 61,4% da diferença apurada."


class ExplicacoesFalsas:
    """`explicacoes`, `prompts` e `respostas_modelo` do job e o provedor do nó."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, job: Job, respostas: list[Any]) -> None:
        self.job = job
        self.modelo = FakeChatModel(messages=iter(respostas))
        self.linhas: dict[UUID, tuple[ExplicacaoGravada, str]] = {}
        self.prompts: list[str] = []
        monkeypatch.setattr(modulo, "get_model", lambda _: self.modelo)
        monkeypatch.setattr(modulo, "buscar_totais_apurados", self.totais)
        monkeypatch.setattr(modulo, "buscar_decomposicao", self.decomposicao)
        monkeypatch.setattr(modulo, "buscar_explicacao", self.buscar)
        monkeypatch.setattr(modulo, "gravar_chamada_e_explicacao", self.gravar)

    async def totais(self, sessoes: Any, job_id: UUID, resultado_id: UUID) -> dict[str, Decimal]:
        _, simulado = self.job.historico.resultados[resultado_id]
        diferenca = simulado - BASELINE
        return {
            "baseline": BASELINE,
            "simulado": simulado,
            "diferenca_abs": diferenca,
            "diferenca_pct": (diferenca / BASELINE).quantize(Decimal("0.0001")),
            "orcamento": self.job.orcamento,
        }

    async def decomposicao(
        self, sessoes: Any, job_id: UUID, resultado_id: UUID
    ) -> dict[str, dict[str, Decimal]]:
        _, simulado = self.job.historico.resultados[resultado_id]
        diferenca = simulado - BASELINE
        return {
            "elemento": {"nucleo.percentual": diferenca},
            "loja": {"13": diferenca},
            "marca": {"10": diferenca},
            "cargo": {"100": diferenca},
            "competencia": {"2025-09": diferenca},
        }

    async def buscar(
        self, sessoes: Any, *, job_id: UUID, resultado_id: UUID, no: str
    ) -> ExplicacaoGravada | None:
        gravada = self.linhas.get(resultado_id)
        return None if gravada is None else gravada[0]

    async def gravar(
        self,
        sessoes: Any,
        *,
        job_id: UUID,
        resultado_id: UUID,
        no: str,
        prompt: str,
        resposta: str,
        conferida: bool | None,
        **_: Any,
    ) -> tuple[UUID, UUID | None]:
        self.prompts.append(prompt)
        prompt_id = id_do_prompt(job_id, no, prompt, resposta)
        if conferida is None:
            return prompt_id, None
        explicacao_id = id_da_explicacao(resultado_id)
        self.linhas[resultado_id] = (
            ExplicacaoGravada(explicacao_id, conferida, prompt_id),
            resposta,
        )
        return prompt_id, explicacao_id


def _explicacoes(job: Job) -> list[dict[str, Any]]:
    return [p for p in job.publicadas("no-concluido") if p["no"] == "explicacao"]


def _nos(job: Job) -> list[str]:
    return [p["no"] for p in job.publicadas("no-concluido")]


def _amostra(texto: str, nome: str, **rotulos: str) -> float:
    return next(
        (
            a.value
            for f in text_string_to_metric_families(texto)
            for a in f.samples
            if a.name == nome and a.labels == rotulos
        ),
        0.0,
    )


def _resposta(texto: str) -> AIMessage:
    return AIMessage(content=texto)


async def test_simulacao_inviavel_e_explicada_antes_da_sugestao_e_o_ciclo_segue(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],  # noqa: F811
) -> None:
    job = Job(monkeypatch)
    explicacoes = ExplicacoesFalsas(monkeypatch, job, [_resposta(NARRATIVA_CONFERIDA)])
    regra = job.original()
    await job.abrir_ciclo(regra)
    antes = (await cliente.get("/metrics")).text

    resultado = await job.simular(regra, SIMULADO)

    assert _nos(job)[-3:] == ["decisao", "explicacao", "sugestao_adaptacao"]
    [trilha] = _explicacoes(job)
    assert trilha["conclusao"]["desfecho_explicacao"] == "conferida"
    assert trilha["resultado_id"] == resultado["resultado_id"]
    assert trilha["regra_id"] == str(regra)
    assert trilha["explicacao_id"] == str(id_da_explicacao(UUID(resultado["resultado_id"])))
    assert UUID(trilha["prompt_id"])
    gravada, texto = explicacoes.linhas[UUID(resultado["resultado_id"])]
    assert gravada.aderencia_conferida is True
    assert texto == NARRATIVA_CONFERIDA
    assert len(job.propostas()) == 1
    depois = (await cliente.get("/metrics")).text
    medida = "codegen_explicacoes_total"
    assert (
        _amostra(depois, medida, desfecho="conferida")
        - _amostra(antes, medida, desfecho="conferida")
        == 1
    )
    duracao = "job_duration_seconds_count"
    assert (
        _amostra(depois, duracao, job_name="explain_result")
        - _amostra(antes, duracao, job_name="explain_result")
        == 1
    )
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    for log in logs:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(log)
    escritos = simplejson.dumps(logs)
    assert NARRATIVA_CONFERIDA not in escritos
    assert formatar_reais(SIMULADO) not in escritos


async def test_o_prompt_gravado_nao_traz_a_quebra_por_matricula(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job(monkeypatch)
    explicacoes = ExplicacoesFalsas(monkeypatch, job, [_resposta(NARRATIVA_CONFERIDA)])
    regra = job.original()
    await job.abrir_ciclo(regra)

    await job.simular(regra, SIMULADO)

    [prompt] = explicacoes.prompts
    assert "MATRIC" not in prompt
    assert "Comissionamento simulado pela regra proposta no período" in prompt
    assert LOJA_FORA_DA_REGRA not in prompt


async def test_narrativa_com_porcentagem_calculada_e_reprovada_e_o_ciclo_segue(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient
) -> None:
    job = Job(monkeypatch)
    explicacoes = ExplicacoesFalsas(monkeypatch, job, [_resposta(NARRATIVA_REPROVADA)])
    regra = job.original()
    await job.abrir_ciclo(regra)
    antes = (await cliente.get("/metrics")).text

    resultado = await job.simular(regra, SIMULADO)

    [trilha] = _explicacoes(job)
    assert trilha["conclusao"]["desfecho_explicacao"] == "reprovada"
    gravada, texto = explicacoes.linhas[UUID(resultado["resultado_id"])]
    assert gravada.aderencia_conferida is False
    assert texto == NARRATIVA_REPROVADA
    assert trilha["explicacao_id"] == str(gravada.id)
    assert _nos(job)[-1] == "sugestao_adaptacao"
    assert len(job.propostas()) == 1
    depois = (await cliente.get("/metrics")).text
    medida = "codegen_explicacoes_total"
    assert (
        _amostra(depois, medida, desfecho="reprovada")
        - _amostra(antes, medida, desfecho="reprovada")
        == 1
    )


class ErroDoProvedorError(Exception):
    code = 503


async def test_com_o_provedor_fora_do_ar_a_etapa_nao_grava_e_o_ciclo_segue_para_a_sugestao(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient
) -> None:
    job = Job(monkeypatch)
    explicacoes = ExplicacoesFalsas(monkeypatch, job, [])
    explicacoes.modelo = MagicMock(ainvoke=AsyncMock(side_effect=ErroDoProvedorError("x")))
    regra = job.original()
    await job.abrir_ciclo(regra)
    antes = (await cliente.get("/metrics")).text

    await job.simular(regra, SIMULADO)

    [trilha] = _explicacoes(job)
    assert trilha["conclusao"]["desfecho_explicacao"] == "provedor_indisponivel"
    assert "explicacao_id" not in trilha
    assert explicacoes.linhas == {}
    assert _nos(job)[-3:] == ["decisao", "explicacao", "sugestao_adaptacao"]
    assert len(job.propostas()) == 1
    assert job.etapas("erro") == []
    depois = (await cliente.get("/metrics")).text
    medida = "codegen_explicacoes_total"
    assert (
        _amostra(depois, medida, desfecho="provedor_indisponivel")
        - _amostra(antes, medida, desfecho="provedor_indisponivel")
        == 1
    )


async def test_simulacao_viavel_tambem_e_explicada_e_termina_sem_proposta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job(monkeypatch)
    ExplicacoesFalsas(monkeypatch, job, [_resposta(NARRATIVA_CONFERIDA)])
    regra = job.original()
    await job.abrir_ciclo(regra)

    await job.simular(regra, Decimal("1650"))

    assert _nos(job)[-2:] == ["decisao", "explicacao"]
    assert job.propostas() == []


async def test_simulacao_com_erro_de_codigo_nao_passa_pela_etapa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job(monkeypatch)
    explicacoes = ExplicacoesFalsas(monkeypatch, job, [_resposta(NARRATIVA_CONFERIDA)])
    worker = Worker(job, monkeypatch)
    regra = job.original()
    await job.abrir_ciclo(regra)

    await worker.falhar(regra)

    assert _explicacoes(job) == []
    assert explicacoes.modelo.seen_messages == []
    assert explicacoes.linhas == {}


async def test_a_reexecucao_depois_da_gravacao_republica_o_mesmo_evento_sem_chamar_o_modelo(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient
) -> None:
    """A trilha da explicação falhou no broker depois de a linha ser gravada; a reentrega do
    resultado reexecuta o nó, que acha a linha, republica a mesma conclusão e não conta de novo."""
    job = Job(monkeypatch)
    explicacoes = ExplicacoesFalsas(monkeypatch, job, [_resposta(NARRATIVA_CONFERIDA)])
    regra = job.original()
    await job.abrir_ciclo(regra)
    recusadas = job.recusar_uma_trilha(lambda p: p["no"] == "explicacao")
    resultado = job.resultado_do_worker(regra, SIMULADO)
    interrompida = await job.entregar(resultado)
    interrompida.nack.assert_awaited_once_with(requeue=True)
    depois_da_falha = (await cliente.get("/metrics")).text

    repetida = await job.entregar(resultado)

    repetida.ack.assert_awaited_once_with()
    [recusada] = recusadas
    [republicada] = _explicacoes(job)
    assert republicada["evento_id"] == recusada["evento_id"]
    assert republicada["conclusao"] == recusada["conclusao"]
    assert republicada["explicacao_id"] == recusada["explicacao_id"]
    assert republicada["prompt_id"] == recusada["prompt_id"]
    assert len(explicacoes.modelo.seen_messages) == 1
    assert len(explicacoes.prompts) == 1
    depois = (await cliente.get("/metrics")).text
    medida = "codegen_explicacoes_total"
    assert _amostra(depois, medida, desfecho="conferida") == _amostra(
        depois_da_falha, medida, desfecho="conferida"
    )
    assert len(job.propostas()) == 1
