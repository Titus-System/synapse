from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.codigo_gerado import CodigoInvalidoError
from app.contratos.mensagens import (
    EtapaAlterada,
    JobEncerrado,
    OrigemJob,
    ParametrosConfirmados,
    RegraSubmetida,
    SimulacaoConcluida,
    StatusSimulacao,
    StatusTerminal,
    Veredito,
)
from app.falhas import JobEncerradoDuranteEsperaError
from app.graph.entrypoint import ResumeOutcome
from app.graph.nodes.code_generation import ProvedorIndisponivelGeracaoError
from app.mensageria import roteamento as modulo
from app.mensageria.roteamento import (
    ContextoAusenteError,
    GraphRouter,
    JobDesconhecidoError,
    JobEncerradoError,
    RetomadaIndisponivelError,
)
from app.repositorio.encerramentos import EstadoDoEncerramento, JobInexistenteError
from app.repositorio.resultados import ResultadoDesconhecidoError
from tests.app.limpeza_falsa import LimpezaFalsa

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
    roteador = GraphRouter(sessoes=sessoes, producers=producers, limpeza=LimpezaFalsa())

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
    roteador = GraphRouter(sessoes=object(), producers=object(), limpeza=LimpezaFalsa())

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
        "submissao_id": str(SUBMISSAO_ID),
        "orcamento": "485000.00",
    }


async def test_entregar_omite_regra_id_e_orcamento_quando_ausentes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_to_completion = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run_to_completion)
    roteador = GraphRouter(sessoes=object(), producers=object(), limpeza=LimpezaFalsa())

    await roteador.entregar(JOB_ID, _regra_submetida(origem=OrigemJob.VOZ, regra_id=None))

    estado = run_to_completion.call_args.args[1]
    assert "regra_id" not in estado
    assert "orcamento" not in estado


def _confirmacao(**sobrescritas: object) -> ParametrosConfirmados:
    valores: dict[str, object] = {
        "job_id": JOB_ID,
        "regra_id": REGRA_ID,
        "competencias": ["2025-08", "2025-11"],
    }
    valores.update(sobrescritas)
    return ParametrosConfirmados.model_validate(valores)


@pytest.mark.parametrize("evento", [_regra_submetida, _confirmacao])
@pytest.mark.parametrize(
    "meta",
    # Zero e negativa chegam como foram ditas: quem as aponta é a validação de domínio (T-280).
    ["12000000.123456789012345", "0", "-5"],
)
async def test_entregar_leva_a_meta_de_venda_ao_estado_em_texto_decimal_exato(
    monkeypatch: pytest.MonkeyPatch, evento: Any, meta: str
) -> None:
    run_to_completion = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run_to_completion)
    roteador = GraphRouter(sessoes=object(), producers=object(), limpeza=LimpezaFalsa())

    await roteador.entregar(JOB_ID, evento(meta_venda=Decimal(meta)))

    assert run_to_completion.call_args.args[1]["meta_venda"] == meta


@pytest.mark.parametrize("evento", [_regra_submetida, _confirmacao])
async def test_entregar_omite_a_meta_de_venda_quando_o_evento_nao_a_traz(
    monkeypatch: pytest.MonkeyPatch, evento: Any
) -> None:
    run_to_completion = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run_to_completion)
    roteador = GraphRouter(sessoes=object(), producers=object(), limpeza=LimpezaFalsa())

    await roteador.entregar(JOB_ID, evento())

    assert "meta_venda" not in run_to_completion.call_args.args[1]


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
    roteador = GraphRouter(sessoes=object(), producers=producers, limpeza=LimpezaFalsa())

    with pytest.raises(CodigoInvalidoError):
        await roteador.entregar(JOB_ID, _regra_submetida())

    [evento] = producers.etapa_alterada.await_args.args
    assert evento == EtapaAlterada(job_id=JOB_ID, etapa="geracao_codigo", status="erro")


async def test_entregar_leva_a_causa_da_falha_no_aviso_de_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        modulo,
        "run_to_completion",
        AsyncMock(side_effect=ProvedorIndisponivelGeracaoError("segredo")),
    )
    producers = MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=object(), producers=producers, limpeza=LimpezaFalsa())

    with pytest.raises(ProvedorIndisponivelGeracaoError):
        await roteador.entregar(JOB_ID, _regra_submetida())

    [evento] = producers.etapa_alterada.await_args.args
    assert evento == EtapaAlterada(
        job_id=JOB_ID,
        etapa="geracao_codigo",
        status="erro",
        causa="provedor_indisponivel",
    )


async def test_entregar_trata_o_job_encerrado_na_espera_como_job_encerrado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        modulo, "run_to_completion", AsyncMock(side_effect=JobEncerradoDuranteEsperaError)
    )
    producers = MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=object(), producers=producers, limpeza=LimpezaFalsa())

    with pytest.raises(JobEncerradoError):
        await roteador.entregar(JOB_ID, _regra_submetida())

    producers.etapa_alterada.assert_not_awaited()


async def test_entregar_nao_avisa_erro_quando_o_grafo_conclui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(modulo, "run_to_completion", AsyncMock())
    producers = MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=object(), producers=producers, limpeza=LimpezaFalsa())

    await roteador.entregar(JOB_ID, _regra_submetida())

    producers.etapa_alterada.assert_not_awaited()


async def test_entregar_nao_avisa_erro_numa_falha_transitoria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falha transitória segue para a reentrega do broker; o job não morreu ainda."""
    monkeypatch.setattr(modulo, "run_to_completion", AsyncMock(side_effect=RuntimeError("x")))
    producers = MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=object(), producers=producers, limpeza=LimpezaFalsa())

    with pytest.raises(RuntimeError):
        await roteador.entregar(JOB_ID, _regra_submetida())

    producers.etapa_alterada.assert_not_awaited()


async def test_entregar_recusa_confirmacao_sem_contexto_sem_falhar_o_job() -> None:
    roteador = GraphRouter(sessoes=object(), producers=object(), limpeza=LimpezaFalsa())
    mensagem = ParametrosConfirmados(job_id=JOB_ID, regra_id=REGRA_ID)

    with pytest.raises(ContextoAusenteError):
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
    roteador = GraphRouter(sessoes=sessoes, producers=producers, limpeza=LimpezaFalsa())

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
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=LimpezaFalsa())

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
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=LimpezaFalsa())

    with pytest.raises(JobDesconhecidoError):
        await roteador.entregar(JOB_ID, _simulacao_concluida())


async def test_entregar_pede_reentrega_quando_o_grafo_ainda_nao_pausou(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    """Descartar aqui perderia o resultado de uma simulação que já rodou."""
    monkeypatch.setattr(
        modulo, "resume_to_completion", AsyncMock(return_value=ResumeOutcome.NOT_PAUSED_YET)
    )
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=LimpezaFalsa())

    with pytest.raises(RetomadaIndisponivelError):
        await roteador.entregar(JOB_ID, _simulacao_concluida())


async def test_entregar_aceita_a_reentrega_de_um_resultado_ja_consumido(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    monkeypatch.setattr(
        modulo, "resume_to_completion", AsyncMock(return_value=ResumeOutcome.ALREADY_FINISHED)
    )
    producers = MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=object(), producers=producers, limpeza=LimpezaFalsa())

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
    roteador = GraphRouter(sessoes=object(), producers=producers, limpeza=LimpezaFalsa())

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
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=LimpezaFalsa())

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
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=LimpezaFalsa())

    with pytest.raises(JobDesconhecidoError):
        await roteador.entregar(JOB_ID, _simulacao_concluida())

    resume.assert_not_awaited()


async def test_entregar_usa_a_thread_da_regra_submetida(monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run)
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=LimpezaFalsa())

    await roteador.entregar(JOB_ID, _regra_submetida())

    assert run.call_args.args[0] == f"{JOB_ID}:{REGRA_ID}"


async def test_entregar_cai_no_job_quando_a_submissao_ainda_nao_tem_regra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Job de voz chega sem versão formada; o ciclo é do job até ela existir."""
    run = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run)
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=LimpezaFalsa())

    await roteador.entregar(JOB_ID, _regra_submetida(origem=OrigemJob.VOZ, regra_id=None))

    assert run.call_args.args[0] == str(JOB_ID)


# ---- o encerramento do job ----

ENCERRAMENTO = JobEncerrado(
    evento_id=uuid4(),
    job_id=JOB_ID,
    status=StatusTerminal.CANCELADO,
    encerrado_em=datetime(2025, 11, 28, 15, 2, 44, tzinfo=UTC),
)


async def test_o_encerramento_e_registrado_sem_tocar_o_grafo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_to_completion = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run_to_completion)
    limpeza = LimpezaFalsa()
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=limpeza)

    await roteador.entregar(JOB_ID, ENCERRAMENTO)

    assert limpeza.registrados == [ENCERRAMENTO]
    run_to_completion.assert_not_awaited()


async def test_encerramento_de_job_inexistente_e_job_desconhecido() -> None:
    """Uma reentrega não faz o job aparecer em `jobs`: a mensagem é rejeitada."""
    limpeza = LimpezaFalsa()
    limpeza.erro_ao_registrar = JobInexistenteError(str(JOB_ID))
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=limpeza)

    with pytest.raises(JobDesconhecidoError):
        await roteador.entregar(JOB_ID, ENCERRAMENTO)


@pytest.mark.parametrize(
    "encerramento", [EstadoDoEncerramento.REGISTRADO, EstadoDoEncerramento.LIMPO]
)
async def test_submissao_de_job_encerrado_nao_recomeca_a_geracao(
    monkeypatch: pytest.MonkeyPatch, encerramento: EstadoDoEncerramento
) -> None:
    run_to_completion = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run_to_completion)
    limpeza = LimpezaFalsa(encerramento)
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=limpeza)

    with pytest.raises(JobEncerradoError):
        await roteador.entregar(JOB_ID, _regra_submetida())

    run_to_completion.assert_not_awaited()
    assert limpeza.limpezas == [(JOB_ID, frozenset())]


async def test_resultado_de_job_ja_limpo_nao_retoma_nada(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    resume = AsyncMock()
    monkeypatch.setattr(modulo, "resume_to_completion", resume)
    limpeza = LimpezaFalsa(EstadoDoEncerramento.LIMPO)
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=limpeza)

    with pytest.raises(JobEncerradoError):
        await roteador.entregar(JOB_ID, _simulacao_concluida())

    resume.assert_not_awaited()
    regra_do_resultado.assert_not_awaited()


async def test_resultado_de_job_encerrado_ainda_e_processado_e_so_depois_limpa(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    """O encerramento pode chegar antes do resultado: os efeitos dele não podem se perder."""
    limpeza = LimpezaFalsa(EstadoDoEncerramento.REGISTRADO)
    ordem: list[str] = []

    async def retomar(*_: object, **__: object) -> ResumeOutcome:
        assert limpeza.em_processamento, "o resultado roda sob o lock compartilhado"
        ordem.append("retomado")
        return ResumeOutcome.RESUMED

    monkeypatch.setattr(modulo, "resume_to_completion", retomar)
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=limpeza)

    await roteador.entregar(JOB_ID, _simulacao_concluida())

    assert ordem == ["retomado"]
    assert limpeza.limpezas == [(JOB_ID, frozenset())]


async def test_retomada_que_falha_de_vez_libera_o_ciclo_para_a_limpeza(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    """A mensagem é rejeitada sem reentrega: nada mais retoma o ciclo, que pode ir embora."""
    monkeypatch.setattr(
        modulo, "resume_to_completion", AsyncMock(side_effect=CodigoInvalidoError("segredo"))
    )
    limpeza = LimpezaFalsa(EstadoDoEncerramento.REGISTRADO)
    producers = MagicMock(etapa_alterada=AsyncMock())
    roteador = GraphRouter(sessoes=object(), producers=producers, limpeza=limpeza)

    with pytest.raises(CodigoInvalidoError):
        await roteador.entregar(JOB_ID, _simulacao_concluida())

    assert limpeza.limpezas == [(JOB_ID, frozenset({f"{JOB_ID}:{REGRA_ID}"}))]
    producers.etapa_alterada.assert_awaited_once()


async def test_retomada_que_sera_reentregue_nao_libera_o_ciclo(
    monkeypatch: pytest.MonkeyPatch, regra_do_resultado: AsyncMock
) -> None:
    """Uma falha transitória volta pela fila: o ciclo ainda vai ser retomado."""
    monkeypatch.setattr(
        modulo, "resume_to_completion", AsyncMock(return_value=ResumeOutcome.NOT_PAUSED_YET)
    )
    limpeza = LimpezaFalsa(EstadoDoEncerramento.REGISTRADO)
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=limpeza)

    with pytest.raises(RetomadaIndisponivelError):
        await roteador.entregar(JOB_ID, _simulacao_concluida())

    assert limpeza.limpezas == [(JOB_ID, frozenset())]


async def test_job_nao_encerrado_segue_normal_e_a_tentativa_de_limpeza_nao_faz_nada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_to_completion = AsyncMock()
    monkeypatch.setattr(modulo, "run_to_completion", run_to_completion)
    limpeza = LimpezaFalsa(None)
    roteador = GraphRouter(sessoes=object(), producers=MagicMock(), limpeza=limpeza)

    await roteador.entregar(JOB_ID, _regra_submetida())

    run_to_completion.assert_awaited_once()
    assert limpeza.limpezas == [(JOB_ID, frozenset())]
