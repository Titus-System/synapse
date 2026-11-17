import logging
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import simplejson
from jsonschema import Draft202012Validator, FormatChecker
from langchain_core.messages import AIMessage
from prometheus_client import REGISTRY

from app.config import get_settings
from app.contratos.serializacao import serializar
from app.core.logger import FormatadorJson, ManipuladorFilaContexto, job_id_ctx
from app.explicacao import montar_numeros_citaveis, narrativa_confere
from app.graph.core.state import AgentState
from app.graph.nodes import explain_result as modulo
from app.graph.nodes.explain_result import ExplicacaoSemResultadoError
from app.prompts.explicacao import montar_prompt_explicacao
from app.repositorio.artefatos import id_do_evento_de_trilha
from app.repositorio.explicacoes import ExplicacaoGravada
from app.repositorio.resultados import ResultadoDesconhecidoError
from tests.app.graph.conftest import FakeChatModel
from tests.app.test_mensageria import oficial

JOB_ID = str(uuid4())
REGRA_ID = str(uuid4())
RESULTADO_ID = str(uuid4())
PROMPT_ID = uuid4()
EXPLICACAO_ID = uuid4()
LOG_SCHEMA = Path(__file__).resolve().parents[5] / "contracts/observability/log.schema.json"

TOTAIS = {
    "baseline": Decimal("480312"),
    "simulado": Decimal("492100"),
    "diferenca_abs": Decimal("11788"),
    "diferenca_pct": Decimal("0.0245"),
    "orcamento": Decimal("485000"),
}
DECOMPOSICAO = {
    "elemento": {"nucleo.percentual": Decimal("11788")},
    "loja": {"13": Decimal("7100"), "58": Decimal("4688")},
    "marca": {"10": Decimal("11788")},
    "cargo": {"100": Decimal("11788")},
    "competencia": {"2025-11": Decimal("11788")},
}
REGRA = {
    "nucleo": {
        "vigencia": {"inicio": "2025-11", "fim": "2025-11"},
        "loja": ["13", "58"],
        "marca": ["10"],
        "cargo": ["100"],
        "percentual": Decimal("0.025"),
    },
    "especificacoes": [],
}
# A narrativa que cita o simulado em reais, a diferença em percentual, uma loja pelo código e a
# competência, cada um como a lista os mostra.
NARRATIVA_CONFERIDA = (
    "Em novembro de 2025 a regra simulou R$ 492.100,00, uma diferença de 2,45% sobre o "
    "baseline. A loja 13 concentrou R$ 7.100,00 dessa diferença."
)
# A participação da loja 13 na diferença é uma conta que ninguém fez.
NARRATIVA_REPROVADA = "A loja 13 respondeu por 60,2% da diferença de R$ 11.788,00."


class Ambiente:
    """O banco e o modelo do nó, no lugar das consultas e do provedor reais."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, respostas: list[AIMessage]) -> None:
        self.modelo = FakeChatModel(messages=iter(respostas))
        self.gravada: ExplicacaoGravada | None = None
        self.chamadas_gravadas: list[dict[str, Any]] = []
        self.totais = AsyncMock(return_value=TOTAIS)
        self.decomposicao = AsyncMock(return_value=DECOMPOSICAO)
        monkeypatch.setattr(modulo, "get_model", lambda nome: self.modelo)
        monkeypatch.setattr(modulo, "buscar_totais_apurados", self.totais)
        monkeypatch.setattr(modulo, "buscar_decomposicao", self.decomposicao)
        monkeypatch.setattr(modulo, "buscar_explicacao", self.buscar_explicacao)
        monkeypatch.setattr(modulo, "gravar_chamada_e_explicacao", self.gravar)
        self.producers = MagicMock(no_concluido=AsyncMock())

    async def buscar_explicacao(self, sessoes: Any, **_: Any) -> ExplicacaoGravada | None:
        return self.gravada

    async def gravar(self, sessoes: Any, **argumentos: Any) -> tuple[UUID, UUID | None]:
        self.chamadas_gravadas.append(argumentos)
        return PROMPT_ID, None if argumentos["conferida"] is None else EXPLICACAO_ID

    @property
    def config(self) -> Any:
        return {"configurable": {"producers": self.producers, "sessoes": "sessoes-falsas"}}

    def publicado(self) -> dict[str, Any]:
        [evento] = self.producers.no_concluido.await_args.args
        payload: dict[str, Any] = simplejson.loads(serializar(evento), use_decimal=True)
        oficial("no-concluido").validate(payload)
        return payload


def _estado(**sobrescritas: Any) -> AgentState:
    estado: AgentState = {
        "job_id": JOB_ID,
        "regra_id": REGRA_ID,
        "resultado_id": RESULTADO_ID,
        "status_simulacao": "sucesso",
        "veredito": "inviavel",
        "competencias": ["2025-11"],
        "representacao_regra": REGRA,
    }
    estado.update(sobrescritas)  # type: ignore[typeddict-item]
    return estado


def _resposta(texto: str, **metadados: Any) -> AIMessage:
    return AIMessage(content=texto, response_metadata=metadados)


def contagens() -> dict[str, float]:
    return {
        amostra.labels["desfecho"]: amostra.value
        for familia in REGISTRY.collect()
        if familia.name == "codegen_explicacoes"
        for amostra in familia.samples
        if amostra.name.endswith("_total")
    }


def duracoes() -> float:
    return next(
        (
            amostra.value
            for familia in REGISTRY.collect()
            if familia.name == "job_duration_seconds"
            for amostra in familia.samples
            if amostra.name.endswith("_count") and amostra.labels["job_name"] == "explain_result"
        ),
        0.0,
    )


def falhas() -> float:
    return next(
        (
            amostra.value
            for familia in REGISTRY.collect()
            if familia.name == "job_failures"
            for amostra in familia.samples
            if amostra.name.endswith("_total") and amostra.labels["job_name"] == "explain_result"
        ),
        0.0,
    )


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
    token = job_id_ctx.set(JOB_ID)
    try:
        yield envelopes
    finally:
        job_id_ctx.reset(token)
        logger.removeHandler(handler)
        logger.setLevel(nivel)


async def test_narrativa_com_numeros_apurados_e_gravada_conferida_e_publicada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = Ambiente(monkeypatch, [_resposta(NARRATIVA_CONFERIDA)])

    await modulo.explain_result(_estado(), ambiente.config)

    [gravacao] = ambiente.chamadas_gravadas
    assert gravacao["conferida"] is True
    assert gravacao["resposta"] == NARRATIVA_CONFERIDA
    assert gravacao["no"] == "explicacao"
    assert gravacao["resultado_id"] == UUID(RESULTADO_ID)
    evento = ambiente.publicado()
    assert evento["evento_id"] == str(
        id_do_evento_de_trilha(UUID(JOB_ID), "explicacao", UUID(RESULTADO_ID))
    )
    assert evento["no"] == "explicacao"
    assert evento["conclusao"]["desfecho_explicacao"] == "conferida"
    assert evento["resultado_id"] == RESULTADO_ID
    assert evento["regra_id"] == REGRA_ID
    assert evento["prompt_id"] == str(PROMPT_ID)
    assert evento["explicacao_id"] == str(EXPLICACAO_ID)


async def test_o_modelo_recebe_exatamente_o_prompt_montado_do_resultado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = Ambiente(monkeypatch, [_resposta(NARRATIVA_CONFERIDA)])

    await modulo.explain_result(_estado(), ambiente.config)

    citaveis = montar_numeros_citaveis(
        totais=TOTAIS,
        decomposicao=DECOMPOSICAO,
        regra=REGRA,
        competencias=["2025-11"],
        meta_venda=None,
    )
    [[mensagem]] = ambiente.modelo.seen_messages
    assert mensagem.content == montar_prompt_explicacao(
        veredito="inviavel", regra=REGRA, citaveis=citaveis
    )
    assert ambiente.chamadas_gravadas[0]["prompt"] == mensagem.content


async def test_narrativa_com_numero_calculado_e_gravada_reprovada_para_o_auditor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = Ambiente(monkeypatch, [_resposta(NARRATIVA_REPROVADA)])

    await modulo.explain_result(_estado(), ambiente.config)

    [gravacao] = ambiente.chamadas_gravadas
    assert gravacao["conferida"] is False
    assert gravacao["resposta"] == NARRATIVA_REPROVADA
    evento = ambiente.publicado()
    assert evento["conclusao"]["desfecho_explicacao"] == "reprovada"
    assert evento["explicacao_id"] == str(EXPLICACAO_ID)


@pytest.mark.parametrize(
    "resposta",
    [
        _resposta("", finish_reason="STOP"),
        _resposta("   \n", finish_reason="STOP"),
        _resposta("Texto cortado", finish_reason="MAX_TOKENS"),
        _resposta("Texto bloqueado", finish_reason="SAFETY"),
    ],
)
async def test_resposta_vazia_ou_interrompida_termina_sem_narrativa_e_grava_so_a_chamada(
    monkeypatch: pytest.MonkeyPatch, resposta: AIMessage
) -> None:
    ambiente = Ambiente(monkeypatch, [resposta])

    await modulo.explain_result(_estado(), ambiente.config)

    [gravacao] = ambiente.chamadas_gravadas
    assert gravacao["conferida"] is None
    evento = ambiente.publicado()
    assert evento["conclusao"]["desfecho_explicacao"] == "sem_resposta"
    assert evento["prompt_id"] == str(PROMPT_ID)
    assert "explicacao_id" not in evento


class ErroDoProvedorError(Exception):
    code = 503


async def test_com_o_provedor_fora_do_ar_a_etapa_termina_sem_linha_e_nao_falha_o_ciclo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = Ambiente(monkeypatch, [])
    ambiente.modelo = MagicMock(
        ainvoke=AsyncMock(side_effect=ErroDoProvedorError("MENSAGEM_PRIVADA"))
    )

    atualizacao = await modulo.explain_result(_estado(), ambiente.config)

    assert atualizacao == {}
    assert ambiente.chamadas_gravadas == []
    evento = ambiente.publicado()
    assert evento["conclusao"]["desfecho_explicacao"] == "provedor_indisponivel"
    assert "explicacao_id" not in evento
    assert "prompt_id" not in evento


async def test_a_reexecucao_depois_da_gravacao_republica_o_mesmo_evento_sem_chamar_o_modelo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = Ambiente(monkeypatch, [_resposta(NARRATIVA_CONFERIDA)])
    await modulo.explain_result(_estado(), ambiente.config)
    primeiro = ambiente.publicado()
    ambiente.gravada = ExplicacaoGravada(EXPLICACAO_ID, True, PROMPT_ID)
    chamadas_do_modelo = len(ambiente.modelo.seen_messages)
    antes = contagens()

    await modulo.explain_result(_estado(), ambiente.config)

    segundo = ambiente.publicado()
    assert segundo["evento_id"] == primeiro["evento_id"]
    assert segundo["conclusao"] == primeiro["conclusao"]
    assert segundo["explicacao_id"] == str(EXPLICACAO_ID)
    assert segundo["prompt_id"] == str(PROMPT_ID)
    assert len(ambiente.modelo.seen_messages) == chamadas_do_modelo
    assert len(ambiente.chamadas_gravadas) == 1
    assert contagens() == antes


async def test_a_reexecucao_de_uma_narrativa_reprovada_republica_como_reprovada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = Ambiente(monkeypatch, [])
    ambiente.gravada = ExplicacaoGravada(EXPLICACAO_ID, False, None)

    await modulo.explain_result(_estado(), ambiente.config)

    evento = ambiente.publicado()
    assert evento["conclusao"]["desfecho_explicacao"] == "reprovada"
    assert "prompt_id" not in evento


async def test_a_quebra_por_matricula_nao_chega_ao_prompt_gravado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = Ambiente(monkeypatch, [_resposta(NARRATIVA_CONFERIDA)])
    ambiente.decomposicao.return_value = DECOMPOSICAO | {
        "matricula": {"MATRIC-422": Decimal("141300")}
    }

    await modulo.explain_result(_estado(), ambiente.config)

    assert "MATRIC-422" not in ambiente.chamadas_gravadas[0]["prompt"]
    assert "141.300" not in ambiente.chamadas_gravadas[0]["prompt"]


async def test_sem_competencias_no_estado_o_periodo_vem_da_decomposicao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = Ambiente(monkeypatch, [_resposta(NARRATIVA_CONFERIDA)])
    estado = _estado()
    del estado["competencias"]

    await modulo.explain_result(estado, ambiente.config)

    assert "Competência simulada: 2025-11" in ambiente.chamadas_gravadas[0]["prompt"]


async def test_o_resultado_sem_totais_falha_o_job_e_conta_a_falha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = Ambiente(monkeypatch, [])
    ambiente.totais.side_effect = ResultadoDesconhecidoError("sem totais")
    antes = falhas()

    with pytest.raises(ExplicacaoSemResultadoError):
        await modulo.explain_result(_estado(), ambiente.config)

    assert falhas() == antes + 1
    ambiente.producers.no_concluido.assert_not_awaited()


@pytest.mark.parametrize(
    ("resposta", "desfecho"),
    [
        (_resposta(NARRATIVA_CONFERIDA), "conferida"),
        (_resposta(NARRATIVA_REPROVADA), "reprovada"),
        (_resposta(""), "sem_resposta"),
    ],
)
async def test_o_contador_e_a_duracao_acompanham_o_processamento_de_cada_desfecho(
    monkeypatch: pytest.MonkeyPatch, resposta: AIMessage, desfecho: str
) -> None:
    ambiente = Ambiente(monkeypatch, [resposta])
    antes, duracoes_antes = contagens(), duracoes()

    await modulo.explain_result(_estado(), ambiente.config)

    depois = contagens()
    assert depois[desfecho] - antes.get(desfecho, 0.0) == 1
    assert sum(depois.values()) - sum(antes.values()) == 1
    assert duracoes() == duracoes_antes + 1


async def test_o_provedor_fora_do_ar_e_contado_com_a_duracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = Ambiente(monkeypatch, [])
    ambiente.modelo = MagicMock(ainvoke=AsyncMock(side_effect=ErroDoProvedorError("x")))
    antes, duracoes_antes = contagens(), duracoes()

    await modulo.explain_result(_estado(), ambiente.config)

    assert contagens()["provedor_indisponivel"] - antes.get("provedor_indisponivel", 0.0) == 1
    assert duracoes() == duracoes_antes + 1


async def test_os_logs_trazem_so_o_desfecho_e_nenhum_conteudo(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    ambiente = Ambiente(monkeypatch, [_resposta(NARRATIVA_REPROVADA)])

    await modulo.explain_result(_estado(), ambiente.config)

    schema = simplejson.loads(LOG_SCHEMA.read_bytes())
    nos_logs = [log for log in logs if log.get("no") == "explicacao"]
    assert [log["message"] for log in nos_logs] == ["explanation started", "explanation finished"]
    for log in nos_logs:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(log)
        assert log["job_id"] == JOB_ID
    assert nos_logs[-1]["extra"] == {"desfecho": "reprovada"}
    serializado = simplejson.dumps(logs)
    for conteudo in ("60,2%", "11.788", "492.100", "Você explica", "Núcleo da regra"):
        assert conteudo not in serializado


async def test_a_falha_do_provedor_nao_leva_a_mensagem_dele_ao_log(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    ambiente = Ambiente(monkeypatch, [])
    ambiente.modelo = MagicMock(
        ainvoke=AsyncMock(side_effect=ErroDoProvedorError("MENSAGEM_PRIVADA com o prompt"))
    )

    await modulo.explain_result(_estado(), ambiente.config)

    assert any(log["message"] == "explanation model call failed" for log in logs)
    assert "MENSAGEM_PRIVADA" not in simplejson.dumps(logs)


async def test_o_contexto_do_no_e_limpo_ao_terminar_inclusive_na_falha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.logger import no_ctx

    ambiente = Ambiente(monkeypatch, [])
    ambiente.totais.side_effect = ResultadoDesconhecidoError("sem totais")

    with pytest.raises(ExplicacaoSemResultadoError):
        await modulo.explain_result(_estado(), ambiente.config)

    assert no_ctx.get() is None


@pytest.mark.llm
@pytest.mark.skipif(not get_settings().GOOGLE_API_KEY, reason="requer GOOGLE_API_KEY")
async def test_explain_result_calls_the_real_provider_and_checks_the_narrative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uma chamada real: o desfecho depende do que o modelo escreve, então o teste confere que o
    nó conclui com um dos desfechos do contrato e que a linha gravada é a que foi conferida."""
    ambiente = Ambiente(monkeypatch, [])
    monkeypatch.undo()
    monkeypatch.setattr(modulo, "buscar_totais_apurados", ambiente.totais)
    monkeypatch.setattr(modulo, "buscar_decomposicao", ambiente.decomposicao)
    monkeypatch.setattr(modulo, "buscar_explicacao", ambiente.buscar_explicacao)
    monkeypatch.setattr(modulo, "gravar_chamada_e_explicacao", ambiente.gravar)

    await modulo.explain_result(_estado(), ambiente.config)

    evento = ambiente.publicado()
    desfecho = evento["conclusao"]["desfecho_explicacao"]
    if desfecho == "provedor_indisponivel":
        pytest.skip("provedor indisponível na explicação")
    [gravacao] = ambiente.chamadas_gravadas
    citaveis = montar_numeros_citaveis(
        totais=TOTAIS,
        decomposicao=DECOMPOSICAO,
        regra=REGRA,
        competencias=["2025-11"],
        meta_venda=None,
    )
    assert desfecho in ("conferida", "reprovada")
    assert gravacao["conferida"] is narrativa_confere(gravacao["resposta"], citaveis)
