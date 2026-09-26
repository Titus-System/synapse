from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.codigo_gerado import CodigoInvalidoError
from app.contratos.mensagens import (
    EtapaAlterada,
    OrigemJob,
    RegraSubmetida,
    SimulacaoConcluida,
    StatusSimulacao,
    Veredito,
)
from app.graph.entrypoint import ResumeOutcome
from app.mensageria import roteamento as modulo
from app.mensageria.roteamento import (
    GraphRouter,
    JobDesconhecidoError,
    RetomadaIndisponivelError,
)
from app.repositorio.resultados import ResultadoDesconhecidoError

JOB_ID = uuid4()
REGRA_ID = uuid4()
SUBMISSAO_ID = uuid4()
RESULTADO_ID = uuid4()


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


async def test_entregar_chama_o_grafo_com_a_thread_do_ciclo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_to_completion = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run_to_completion)
    sessoes, producers = object(), object()
    roteador = GraphRouter(sessoes=sessoes, producers=producers)

    await roteador.entregar(JOB_ID, _regra_submetida())

    run_to_completion.assert_awaited_once()
    argumentos, nomeados = run_to_completion.call_args
    assert argumentos[0] == f"{JOB_ID}:{REGRA_ID}"
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


@pytest.fixture
def regra_do_resultado(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """`simulacao-concluida` não carrega a versão da regra; ela vem do banco."""
    busca = AsyncMock(return_value=REGRA_ID)
    monkeypatch.setattr(modulo, "buscar_regra_do_resultado", busca)
    return busca


def _simulacao_concluida(**sobrescritas: object) -> SimulacaoConcluida:
    valores: dict[str, object] = {
        "job_id": JOB_ID,
        "resultado_id": RESULTADO_ID,
        "status": StatusSimulacao.SUCESSO,
        "veredito": Veredito.INVIAVEL,
        "total_baseline": Decimal("480000.00"),
        "total_simulado": Decimal("492100.00"),
    }
    valores.update(sobrescritas)
    return SimulacaoConcluida.model_validate(valores)


async def test_entregar_retoma_o_grafo_sem_levar_os_numeros_da_simulacao(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    """Retomada leva referência e controle; os totais ficam em `resultados_simulacao`."""
    resume = AsyncMock(return_value=ResumeOutcome.RESUMED)
    monkeypatch.setattr(modulo, "resume_to_completion", resume)
    sessoes, producers = object(), MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=sessoes, producers=producers)

    await roteador.entregar(JOB_ID, _simulacao_concluida())

    argumentos, nomeados = resume.call_args
    assert argumentos[0] == f"{JOB_ID}:{REGRA_ID}"
    assert argumentos[1] == {
        "resultado_id": str(RESULTADO_ID),
        "status": StatusSimulacao.SUCESSO,
        "veredito": Veredito.INVIAVEL,
    }
    assert nomeados == {"sessoes": sessoes, "producers": producers}


async def test_entregar_retoma_sem_veredito_quando_a_execucao_nao_teve_sucesso(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    monkeypatch.setattr(
        modulo, "resume_to_completion", AsyncMock(return_value=ResumeOutcome.RESUMED)
    )
    roteador = GraphRouter(sessoes=object(), producers=MagicMock())

    await roteador.entregar(
        JOB_ID,
        _simulacao_concluida(status=StatusSimulacao.ERRO_INFRA, veredito=None, total_simulado=None),
    )

    valor = modulo.resume_to_completion.call_args.args[1]  # type: ignore[attr-defined]
    assert valor["veredito"] is None


async def test_entregar_rejeita_resultado_de_job_sem_grafo(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    monkeypatch.setattr(
        modulo, "resume_to_completion", AsyncMock(return_value=ResumeOutcome.NO_CHECKPOINT)
    )
    roteador = GraphRouter(sessoes=object(), producers=MagicMock())

    with pytest.raises(JobDesconhecidoError):
        await roteador.entregar(JOB_ID, _simulacao_concluida())


async def test_entregar_pede_reentrega_quando_o_grafo_ainda_nao_pausou(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    """Descartar aqui perderia o resultado de uma simulação que já rodou."""
    monkeypatch.setattr(
        modulo, "resume_to_completion", AsyncMock(return_value=ResumeOutcome.NOT_PAUSED_YET)
    )
    roteador = GraphRouter(sessoes=object(), producers=MagicMock())

    with pytest.raises(RetomadaIndisponivelError):
        await roteador.entregar(JOB_ID, _simulacao_concluida())


async def test_entregar_aceita_a_reentrega_de_um_resultado_ja_consumido(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    monkeypatch.setattr(
        modulo, "resume_to_completion", AsyncMock(return_value=ResumeOutcome.ALREADY_FINISHED)
    )
    producers = MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=object(), producers=producers)

    await roteador.entregar(JOB_ID, _simulacao_concluida())

    producers.etapa_alterada.assert_not_awaited()


async def test_entregar_avisa_a_api_quando_a_retomada_mata_o_job(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    """Falha permanente depois da retomada também precisa tirar o job de `simulando`."""
    monkeypatch.setattr(
        modulo, "resume_to_completion", AsyncMock(side_effect=CodigoInvalidoError("segredo"))
    )
    producers = MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=object(), producers=producers)

    with pytest.raises(CodigoInvalidoError):
        await roteador.entregar(JOB_ID, _simulacao_concluida())

    [evento] = producers.etapa_alterada.await_args.args
    assert evento == EtapaAlterada(job_id=JOB_ID, etapa="geracao_codigo", status="erro")


async def test_entregar_retoma_a_thread_do_ciclo_que_pediu_a_execucao(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    """Um job que adapta a regra tem mais de um ciclo, e cada um tem sua própria thread."""
    outra_regra = uuid4()
    regra_do_resultado.return_value = outra_regra
    resume = AsyncMock(return_value=ResumeOutcome.RESUMED)
    monkeypatch.setattr(modulo, "resume_to_completion", resume)
    roteador = GraphRouter(sessoes=object(), producers=MagicMock())

    await roteador.entregar(JOB_ID, _simulacao_concluida())

    assert resume.call_args.args[0] == f"{JOB_ID}:{outra_regra}"
    regra_do_resultado.assert_awaited_once()


async def test_entregar_rejeita_resultado_que_nao_aponta_para_uma_regra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem a versão não há ciclo a retomar, e reentregar não faria o vínculo aparecer."""
    monkeypatch.setattr(
        modulo,
        "buscar_regra_do_resultado",
        AsyncMock(side_effect=ResultadoDesconhecidoError("sem vínculo")),
    )
    resume = AsyncMock()
    monkeypatch.setattr(modulo, "resume_to_completion", resume)
    roteador = GraphRouter(sessoes=object(), producers=MagicMock())

    with pytest.raises(JobDesconhecidoError):
        await roteador.entregar(JOB_ID, _simulacao_concluida())

    resume.assert_not_awaited()


async def test_entregar_usa_a_thread_da_regra_submetida(monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run)
    roteador = GraphRouter(sessoes=object(), producers=MagicMock())

    await roteador.entregar(JOB_ID, _regra_submetida())

    assert run.call_args.args[0] == f"{JOB_ID}:{REGRA_ID}"


async def test_entregar_cai_no_job_quando_a_submissao_ainda_nao_tem_regra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Job de voz chega sem versão formada; o ciclo é do job até ela existir."""
    run = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run)
    roteador = GraphRouter(sessoes=object(), producers=MagicMock())

    await roteador.entregar(JOB_ID, _regra_submetida(origem=OrigemJob.VOZ, regra_id=None))

    assert run.call_args.args[0] == str(JOB_ID)
