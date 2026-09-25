from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import simplejson
from langchain_core.runnables import RunnableConfig

from app.codigo_gerado import CodigoInvalidoError
from app.contratos.mensagens import EtapaAlterada, ExecutarCodigo
from app.contratos.serializacao import serializar
from app.graph.core.state import AgentState
from app.graph.nodes.dispatch_execution import OrcamentoAusenteError, dispatch_execution
from app.graph.nodes.extract_code import extract_code
from app.graph.nodes.persist_response import persist_response
from tests.app.banco_falso import BancoFalso
from tests.app.test_mensageria import oficial

JOB_ID = str(uuid4())
REGRA_ID = str(uuid4())
FONTE = "def aplicar_regra(bases, apuracao_base, competencias):\n    return {}\n"
RESPOSTA = f"```python\n{FONTE}```"


def _producers() -> Any:
    return MagicMock(
        executar_codigo=AsyncMock(), etapa_alterada=AsyncMock(), no_concluido=AsyncMock()
    )


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

    update = await extract_code(_estado(prompt_id=prompt_id), _config(banco, _producers()))

    [codigo] = banco.tabela("codigos_gerados")
    assert codigo["fonte"] == FONTE
    assert codigo["prompt_id"] == UUID(prompt_id)
    assert codigo["regra_id"] == UUID(REGRA_ID)
    assert update == {"codigo_fonte": FONTE, "codigo_gerado_id": str(codigo["id"])}


async def test_extract_code_anuncia_a_conclusao_do_no_com_as_referencias() -> None:
    """Sem este evento a api não cria a linha de `simulacoes`, e é ela que liga o job ao
    resultado do worker - o cliente nunca receberia o evento SSE `resultado`."""
    banco = BancoFalso()
    producers = _producers()
    prompt_id = str(uuid4())

    update = await extract_code(_estado(prompt_id=prompt_id), _config(banco, producers))

    [evento] = producers.no_concluido.await_args.args
    assert evento.no == "geracao_codigo"
    assert evento.job_id == UUID(JOB_ID)
    assert evento.regra_id == UUID(REGRA_ID)
    assert evento.prompt_id == UUID(prompt_id)
    assert evento.codigo_gerado_id == UUID(update["codigo_gerado_id"])
    assert evento.concluido_em.tzinfo is not None
    assert evento.conclusao.resumo
    # A cobertura dos elementos é conferência de outro nó (T-056): declarar uma lista aqui
    # afirmaria uma verificação que este nó não fez.
    assert evento.conclusao.elementos_implementados is None
    # Nada de artefato no evento: nem o código, nem o prompt, nem a resposta.
    assert FONTE not in serializar(evento).decode()


async def test_extract_code_repete_o_mesmo_evento_id_numa_reexecucao() -> None:
    """O id é a chave de idempotência da trilha na api; reexecutar o nó não pode duplicá-la."""
    estado = _estado(prompt_id=str(uuid4()))
    primeiro, segundo = _producers(), _producers()

    await extract_code(estado, _config(BancoFalso(), primeiro))
    await extract_code(estado, _config(BancoFalso(), segundo))

    assert (
        primeiro.no_concluido.await_args.args[0].evento_id
        == segundo.no_concluido.await_args.args[0].evento_id
    )


async def test_extract_code_publica_um_payload_valido_no_contrato() -> None:
    producers = _producers()

    await extract_code(_estado(prompt_id=str(uuid4())), _config(BancoFalso(), producers))

    [evento] = producers.no_concluido.await_args.args
    oficial("no-concluido").validate(simplejson.loads(serializar(evento), use_decimal=True))


async def test_extract_code_falha_sem_gravar_quando_a_resposta_e_invalida() -> None:
    banco = BancoFalso()
    producers = _producers()

    with pytest.raises(CodigoInvalidoError):
        await extract_code(
            _estado(prompt_id=str(uuid4()), resposta_bruta="sem código"),
            _config(banco, producers),
        )

    assert banco.tabela("codigos_gerados") == []
    producers.no_concluido.assert_not_awaited()


async def test_extract_code_nao_anuncia_conclusao_se_a_gravacao_falhou() -> None:
    """O evento leva a referência de uma linha que tem de existir antes dele (claim-check)."""
    banco = BancoFalso(falhar_em=("codigos_gerados",))
    producers = _producers()

    with pytest.raises(RuntimeError):
        await extract_code(_estado(prompt_id=str(uuid4())), _config(banco, producers))

    producers.no_concluido.assert_not_awaited()


async def test_dispatch_execution_publica_so_referencias() -> None:
    producers = _producers()
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


async def test_dispatch_execution_anuncia_a_delegacao_antes_de_publicar_o_comando() -> None:
    """A ordem é a garantia: o evento idempotente vai na frente do comando que não é.

    Assim uma reexecução do nó arrisca duplicar só o comando, e o job já está em `simulando`
    antes de o worker poder concluir.
    """
    producers = _producers()

    await dispatch_execution(_estado(codigo_gerado_id=str(uuid4())), _config(producers=producers))

    assert [chamada[0] for chamada in producers.method_calls] == [
        "etapa_alterada",
        "executar_codigo",
    ]
    [evento] = producers.etapa_alterada.await_args.args
    assert evento == EtapaAlterada(job_id=UUID(JOB_ID), etapa="delegacao_worker", status="iniciada")


async def test_dispatch_execution_falha_sem_publicar_quando_falta_orcamento() -> None:
    producers = _producers()
    estado = _estado(codigo_gerado_id=str(uuid4()))
    del estado["orcamento"]

    with pytest.raises(OrcamentoAusenteError):
        await dispatch_execution(estado, _config(producers=producers))

    producers.executar_codigo.assert_not_awaited()
    producers.etapa_alterada.assert_not_awaited()
