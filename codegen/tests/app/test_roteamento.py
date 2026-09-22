from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.contratos.mensagens import OrigemJob, RegraSubmetida
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
