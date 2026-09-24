from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from langchain_core.runnables import RunnableConfig

from app.codigo_gerado import CodigoInvalidoError
from app.contratos.mensagens import ExecutarCodigo
from app.graph.core.state import AgentState
from app.graph.nodes.dispatch_execution import OrcamentoAusenteError, dispatch_execution
from app.graph.nodes.extract_code import extract_code
from app.graph.nodes.persist_response import persist_response
from tests.app.banco_falso import BancoFalso

JOB_ID = str(uuid4())
REGRA_ID = str(uuid4())
FONTE = "def aplicar_regra(bases, apuracao_base, competencias):\n    return {}\n"
RESPOSTA = f"```python\n{FONTE}```"


def _config(banco: BancoFalso | None = None, producers: Any = None) -> RunnableConfig:
    return {"configurable": {"sessoes": banco, "producers": producers}}


def _estado(**sobrescritas: Any) -> AgentState:
    estado: AgentState = {
        "job_id": JOB_ID,
        "regra_id": REGRA_ID,
        "competencias": ["2025-08", "2025-11"],
        "orcamento": "485000.10",
        "prompt_enviado": "prompt",
        "resposta_bruta": RESPOSTA,
        "modelo": {"provedor": "google", "modelo": "m", "versao": "stable"},
    }
    estado.update(sobrescritas)  # type: ignore[typeddict-item]
    return estado


async def test_persist_response_grava_e_devolve_os_ids() -> None:
    banco = BancoFalso()

    update = await persist_response(_estado(), _config(banco))

    [prompt] = banco.tabela("prompts")
    [resposta] = banco.tabela("respostas_modelo")
    assert prompt["no"] == "geracao_codigo"
    assert resposta["conteudo"] == RESPOSTA
    assert update == {"prompt_id": str(prompt["id"]), "resposta_id": str(resposta["id"])}


async def test_extract_code_grava_o_codigo_ligado_ao_prompt_e_a_regra() -> None:
    banco = BancoFalso()
    prompt_id = str(uuid4())

    update = await extract_code(_estado(prompt_id=prompt_id), _config(banco))

    [codigo] = banco.tabela("codigos_gerados")
    assert codigo["fonte"] == FONTE
    assert codigo["prompt_id"] == UUID(prompt_id)
    assert codigo["regra_id"] == UUID(REGRA_ID)
    assert update == {"codigo_fonte": FONTE, "codigo_gerado_id": str(codigo["id"])}


async def test_extract_code_falha_sem_gravar_quando_a_resposta_e_invalida() -> None:
    banco = BancoFalso()

    with pytest.raises(CodigoInvalidoError):
        await extract_code(
            _estado(prompt_id=str(uuid4()), resposta_bruta="sem código"), _config(banco)
        )

    assert banco.tabela("codigos_gerados") == []


async def test_dispatch_execution_publica_so_referencias() -> None:
    producers = MagicMock(executar_codigo=AsyncMock())
    codigo_gerado_id = str(uuid4())

    await dispatch_execution(
        _estado(codigo_gerado_id=codigo_gerado_id), _config(producers=producers)
    )

    [comando] = producers.executar_codigo.await_args.args
    assert comando == ExecutarCodigo(
        job_id=UUID(JOB_ID),
        codigo_gerado_id=UUID(codigo_gerado_id),
        competencias=["2025-08", "2025-11"],
        orcamento=Decimal("485000.10"),
    )


async def test_dispatch_execution_falha_sem_publicar_quando_falta_orcamento() -> None:
    producers = MagicMock(executar_codigo=AsyncMock())
    estado = _estado(codigo_gerado_id=str(uuid4()))
    del estado["orcamento"]

    with pytest.raises(OrcamentoAusenteError):
        await dispatch_execution(estado, _config(producers=producers))

    producers.executar_codigo.assert_not_awaited()
