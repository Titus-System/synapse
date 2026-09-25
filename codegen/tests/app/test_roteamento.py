from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.codigo_gerado import CodigoInvalidoError
from app.contratos.mensagens import EtapaAlterada, OrigemJob, RegraSubmetida
from app.mensageria import roteamento as modulo
from app.mensageria.roteamento import GraphRouter

JOB_ID = uuid4()
REGRA_ID = uuid4()
SUBMISSAO_ID = uuid4()


def _regra_submetida(**sobrescritas: object) -> RegraSubmetida:
    valores: dict[str, object] = {
        "job_id": JOB_ID,
        "origem": OrigemJob.FORMULARIO,
        "competencias": ["2025-08", "2025-11"],
        "submissao_id": SUBMISSAO_ID,
        "regra_id": REGRA_ID,
    }
    valores.update(sobrescritas)
    return RegraSubmetida.model_validate(valores)


async def test_entregar_chama_o_grafo_com_o_job_id_como_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_to_completion = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run_to_completion)
    sessoes, producers = object(), object()
    roteador = GraphRouter(sessoes=sessoes, producers=producers)

    await roteador.entregar(JOB_ID, _regra_submetida())

    run_to_completion.assert_awaited_once()
    argumentos, nomeados = run_to_completion.call_args
    assert argumentos[0] == str(JOB_ID)
    assert nomeados == {"sessoes": sessoes, "producers": producers}
    assert argumentos[1]["job_id"] == str(JOB_ID)


async def test_entregar_monta_o_estado_inicial_a_partir_do_evento(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_to_completion = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run_to_completion)
    roteador = GraphRouter(sessoes=object(), producers=object())

    await roteador.entregar(
        JOB_ID,
        _regra_submetida(orcamento=Decimal("485000.00"), competencias=["2025-11"]),
    )

    estado = run_to_completion.call_args.args[1]
    assert estado == {
        "job_id": str(JOB_ID),
        "origem": "formulario",
        "competencias": ["2025-11"],
        "regra_id": str(REGRA_ID),
        "orcamento": "485000.00",
    }


async def test_entregar_omite_regra_id_e_orcamento_quando_ausentes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_to_completion = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run_to_completion)
    roteador = GraphRouter(sessoes=object(), producers=object())

    await roteador.entregar(JOB_ID, _regra_submetida(origem=OrigemJob.VOZ, regra_id=None))

    estado = run_to_completion.call_args.args[1]
    assert "regra_id" not in estado
    assert "orcamento" not in estado


async def test_entregar_avisa_a_api_e_repropaga_quando_o_job_falha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem este aviso a `api` deixaria o job em `gerando_regra` para sempre.

    A etapa do evento vem da própria exceção, então o motivo da transição gravado pela `api`
    aponta o passo em que o job morreu.
    """
    monkeypatch.setattr(
        modulo, "run_to_completion", AsyncMock(side_effect=CodigoInvalidoError("segredo"))
    )
    producers = MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=object(), producers=producers)

    with pytest.raises(CodigoInvalidoError):
        await roteador.entregar(JOB_ID, _regra_submetida())

    [evento] = producers.etapa_alterada.await_args.args
    assert evento == EtapaAlterada(job_id=JOB_ID, etapa="geracao_codigo", status="erro")


async def test_entregar_nao_avisa_erro_quando_o_grafo_conclui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(modulo, "run_to_completion", AsyncMock())
    producers = MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=object(), producers=producers)

    await roteador.entregar(JOB_ID, _regra_submetida())

    producers.etapa_alterada.assert_not_awaited()


async def test_entregar_nao_avisa_erro_numa_falha_transitoria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falha transitória segue para a reentrega do broker; o job não morreu ainda."""
    monkeypatch.setattr(modulo, "run_to_completion", AsyncMock(side_effect=RuntimeError("x")))
    producers = MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=object(), producers=producers)

    with pytest.raises(RuntimeError):
        await roteador.entregar(JOB_ID, _regra_submetida())

    producers.etapa_alterada.assert_not_awaited()


async def test_entregar_recusa_mensagens_diferentes_de_regra_submetida() -> None:
    from app.contratos.mensagens import ParametrosConfirmados

    roteador = GraphRouter(sessoes=object(), producers=object())
    mensagem = ParametrosConfirmados(job_id=JOB_ID, regra_id=REGRA_ID)

    with pytest.raises(NotImplementedError):
        await roteador.entregar(JOB_ID, mensagem)


async def test_entregar_recusa_rodar_sem_sessoes_ou_producers_configurados() -> None:
    roteador = GraphRouter()

    with pytest.raises(RuntimeError):
        await roteador.entregar(JOB_ID, _regra_submetida())
