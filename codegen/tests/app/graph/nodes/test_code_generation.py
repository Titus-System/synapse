import logging
import re
from collections.abc import Callable, Iterable

import pytest
from langchain_core.messages import AIMessage

from app.config import get_settings
from app.graph.core.state import AgentState
from app.graph.nodes.code_generation import RespostaModeloInvalidaError, code_generation
from app.prompts.geracao_codigo import montar_prompt_geracao
from app.representacao_regra import RepresentacaoRegra
from tests.app.graph.conftest import FakeChatModel

ScriptedModel = Callable[[Iterable[AIMessage]], FakeChatModel]

_REGRA: AgentState = {"representacao_regra": {"nucleo": {}, "especificacoes": []}}


@pytest.mark.llm
@pytest.mark.skipif(not get_settings().GOOGLE_API_KEY, reason="requer GOOGLE_API_KEY")
async def test_code_generation_calls_the_real_provider_and_returns_one_python_block() -> None:
    update = await code_generation(_REGRA, {"configurable": {}})

    assert re.findall(r"```python\b", update["resposta_bruta"]) == ["```python"]
    assert update["resposta_bruta"].count("```") == 2
    assert update["prompt_enviado"] == montar_prompt_geracao(
        RepresentacaoRegra.model_validate(_REGRA["representacao_regra"])
    )
    assert update["modelo"]["provedor"] == "google"


async def test_code_generation_sends_exactly_the_generation_prompt(
    scripted_model: ScriptedModel,
) -> None:
    model = scripted_model([AIMessage(content="```python\ndef aplicar_regra(): ...\n```")])

    await code_generation(_REGRA, {"configurable": {}})

    regra = RepresentacaoRegra.model_validate(_REGRA["representacao_regra"])
    esperado = montar_prompt_geracao(regra)
    assert [m.content for m in model.seen_messages[0]] == [esperado]


async def test_code_generation_extracts_text_from_a_list_of_content_parts(
    scripted_model: ScriptedModel,
) -> None:
    # Real-provider regression: `langchain_google_genai` can return `AIMessage.content` as a
    # list of part dicts (observed against the real API) instead of a plain `str`, even for an
    # ordinary text reply. A bare `isinstance(content, str)` check treats every one of those as
    # empty and fails the node on every real call - see `Attention.md`.
    resposta = AIMessage(
        content=[
            {"type": "text", "text": "```python\n"},
            {"type": "text", "text": "def aplicar_regra(): ...\n```", "extras": {"x": "y"}},
        ]
    )
    scripted_model([resposta])

    update = await code_generation(_REGRA, {"configurable": {}})

    assert update["resposta_bruta"] == "```python\ndef aplicar_regra(): ...\n```"


async def test_code_generation_returns_prompt_and_raw_response_verbatim(
    scripted_model: ScriptedModel,
) -> None:
    scripted_model([AIMessage(content="```python\ndef aplicar_regra(): ...\n```")])

    update = await code_generation(_REGRA, {"configurable": {}})

    assert update["resposta_bruta"] == "```python\ndef aplicar_regra(): ...\n```"
    assert update["prompt_enviado"] == montar_prompt_geracao(
        RepresentacaoRegra.model_validate(_REGRA["representacao_regra"])
    )


async def test_code_generation_records_model_metadata(scripted_model: ScriptedModel) -> None:
    scripted_model([AIMessage(content="```python\n...\n```")])

    update = await code_generation(_REGRA, {"configurable": {}})

    assert update["modelo"] == {
        "provedor": "google",
        "modelo": "gemini-3.1-flash-lite",
        "versao": "stable",
        "parametros": {"temperature": 0, "max_output_tokens": 8192},
    }


async def test_code_generation_records_token_usage_when_the_provider_reports_it(
    scripted_model: ScriptedModel,
) -> None:
    resposta = AIMessage(
        content="```python\n...\n```",
        usage_metadata={"input_tokens": 120, "output_tokens": 40, "total_tokens": 160},
    )
    scripted_model([resposta])

    update = await code_generation(_REGRA, {"configurable": {}})

    assert update["consumo_tokens"] == {"tokens_in": 120, "tokens_out": 40}


async def test_code_generation_omits_token_usage_when_the_provider_does_not_report_it(
    scripted_model: ScriptedModel,
) -> None:
    scripted_model([AIMessage(content="```python\n...\n```")])

    update = await code_generation(_REGRA, {"configurable": {}})

    assert "consumo_tokens" not in update


async def test_code_generation_raises_on_an_empty_response(scripted_model: ScriptedModel) -> None:
    scripted_model([AIMessage(content="")])

    with pytest.raises(RespostaModeloInvalidaError):
        await code_generation(_REGRA, {"configurable": {}})


@pytest.mark.parametrize("motivo", ["SAFETY", "RECITATION", "MAX_TOKENS", "OTHER"])
async def test_code_generation_raises_when_the_provider_blocks_or_truncates(
    scripted_model: ScriptedModel, motivo: str
) -> None:
    resposta = AIMessage(content="partial", response_metadata={"finish_reason": motivo})
    scripted_model([resposta])

    with pytest.raises(RespostaModeloInvalidaError):
        await code_generation(_REGRA, {"configurable": {}})


async def test_code_generation_never_logs_the_rule_prompt_or_response(
    scripted_model: ScriptedModel, caplog: pytest.LogCaptureFixture
) -> None:
    scripted_model([AIMessage(content="")])

    with (
        caplog.at_level(logging.ERROR, logger="app.graph.nodes.code_generation"),
        pytest.raises(RespostaModeloInvalidaError),
    ):
        await code_generation(_REGRA, {"configurable": {}})

    texto = " ".join(registro.getMessage() for registro in caplog.records)
    assert "aplicar_regra" not in texto
    assert "nucleo" not in texto


def test_code_generation_state_type_accepts_the_fields_it_returns() -> None:
    # Documents the shape returned by the node against `AgentState`'s declared fields.
    update: AgentState = {
        "prompt_enviado": "x",
        "resposta_bruta": "y",
        "modelo": {"provedor": "google", "modelo": "m", "versao": "v"},
        "consumo_tokens": {"tokens_in": 1, "tokens_out": 1},
    }
    assert set(update) == {"prompt_enviado", "resposta_bruta", "modelo", "consumo_tokens"}
