from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contratos.mensagens import (
    EtapaAlterada,
    JobEncerrado,
    ParametrosConfirmados,
    RegraSubmetida,
    SimulacaoConcluida,
)
from app.core.logger import get_logger
from app.core.metrics.global_metrics import parametros_confirmados
from app.falhas import FalhaDoJobError
from app.graph.core.state import AgentState
from app.graph.entrypoint import ResumeOutcome, RunOutcome, resume_to_completion, run_to_completion
from app.mensageria.limpeza import LimpezaDeCheckpoints
from app.mensageria.producers import Producers
from app.repositorio.encerramentos import EstadoDoEncerramento, JobInexistenteError
from app.repositorio.resultados import ResultadoDesconhecidoError, buscar_regra_do_resultado

type Entrada = RegraSubmetida | ParametrosConfirmados | SimulacaoConcluida | JobEncerrado

logger = get_logger("app.mensageria.roteamento")


class ContextoAusenteError(Exception):
    """A confirmação não permite abrir um ciclo; descartá-la não é uma falha do job."""


class JobDesconhecidoError(Exception):
    """O roteador não encontrou o grafo correspondente ao job recebido."""


class JobEncerradoError(Exception):
    """A mensagem é de um job que a `api` já encerrou, e não há o que processar.

    Uma submissão nunca recomeça um job encerrado, e um resultado só é processado enquanto o
    ciclo dele ainda espera: depois da limpeza, a mensagem é reconhecida pelo registro do
    encerramento e confirmada sem efeito, em vez de recriar checkpoints ou repetir publicações.
    """


class RetomadaIndisponivelError(Exception):
    """O grafo existe mas ainda não chegou à pausa: a reentrega do broker é a resposta certa.

    O worker pode publicar o resultado antes de o checkpoint com o `interrupt()` pendente ser
    gravado. Rejeitar a mensagem aqui perderia o resultado de uma simulação que aconteceu.
    """


class RoteadorGrafo(Protocol):
    async def entregar(self, job_id: UUID, mensagem: Entrada) -> None:
        """Retorna só após processamento persistido; reentregas devem ser idempotentes.

        Abre ciclos de regra-submetida e parametros-confirmados, retoma o resultado e registra
        job-encerrado. ContextoAusenteError descarta confirmação sem competências, sem falhar
        o job. Lança JobDesconhecidoError se não houver grafo
        correspondente à mensagem, JobEncerradoError quando a mensagem é de um job já
        encerrado, RetomadaIndisponivelError quando o grafo ainda não chegou à pausa, e
        `app.falhas.FalhaDoJobError` quando o processamento falha de forma permanente - depois de
        avisar a `api`, para que o job termine em erro em vez de ficar pendurado.
        """
        ...


@dataclass
class GraphRouter:
    """Concrete `RoteadorGrafo`: opens a graph cycle for each submitted or confirmed rule.

    `sessoes`, `producers` and `limpeza` are set once by the app's lifespan, after the
    corresponding resource (database engine, broker connection) is ready - see `app/main.py`.

    Every graph message runs under the job's shared lock and checks whether the `api` closed the
    job; `JobEncerrado` registers the closure and starts the checkpoint cleanup - see
    `app/mensageria/limpeza.py`.
    """

    sessoes: async_sessionmaker[AsyncSession] | None = None
    producers: Producers | None = None
    limpeza: LimpezaDeCheckpoints | None = None

    async def entregar(self, job_id: UUID, mensagem: Entrada) -> None:
        if self.sessoes is None or self.producers is None or self.limpeza is None:
            raise RuntimeError("GraphRouter is not fully wired yet")

        if isinstance(mensagem, JobEncerrado):
            try:
                await self.limpeza.registrar(mensagem)
            except JobInexistenteError as erro:
                raise JobDesconhecidoError(str(job_id)) from erro
            return

        # Ciclos cuja mensagem foi assentada sem que eles terminassem: a limpeza pode descartá-los.
        assentados: set[str] = set()
        try:
            async with self.limpeza.durante_o_processamento(job_id) as encerramento:
                _recusar_se_encerrado(job_id, mensagem, encerramento)
                desfecho = await self._processar(
                    job_id, mensagem, self.sessoes, self.producers, assentados
                )
        finally:
            # Fora do lock compartilhado: o encerramento pode ter chegado durante o
            # processamento, e só agora a limpeza consegue o lock exclusivo.
            await self.limpeza.limpar(job_id, frozenset(assentados))

        if isinstance(mensagem, ParametrosConfirmados):
            resultado = "reentrega_ignorada" if desfecho is RunOutcome.IGNORED else "ciclo_aberto"
            parametros_confirmados.labels(resultado=resultado).inc()
            logger.info(
                "confirmação de parâmetros processada",
                extra={
                    "tipo_mensagem": "parametros-confirmados",
                    "resultado": resultado,
                    "regra_id": str(mensagem.regra_id),
                },
            )

    async def _processar(
        self,
        job_id: UUID,
        mensagem: RegraSubmetida | ParametrosConfirmados | SimulacaoConcluida,
        sessoes: async_sessionmaker[AsyncSession],
        producers: Producers,
        assentados: set[str],
    ) -> RunOutcome | None:
        try:
            if isinstance(mensagem, SimulacaoConcluida):
                await self._retomar(job_id, mensagem, sessoes, producers, assentados)
            elif isinstance(mensagem, ParametrosConfirmados):
                return await run_to_completion(
                    thread_do_ciclo(job_id, mensagem.regra_id),
                    _estado_confirmado(mensagem),
                    sessoes=sessoes,
                    producers=producers,
                )
            else:
                await run_to_completion(
                    thread_do_ciclo(job_id, mensagem.regra_id),
                    _estado_inicial(mensagem),
                    sessoes=sessoes,
                    producers=producers,
                )
        except FalhaDoJobError as falha:
            # Esta é a fronteira que sabe que o job acabou: sem este aviso, a `api` deixaria
            # o job em `gerando_regra` para sempre. Uma falha ao publicar não é tratada de
            # propósito - ela sobe como falha comum, o consumer reenfileira e a reentrega
            # tenta avisar de novo. Melhor do que engolir o aviso.
            await producers.etapa_alterada(
                EtapaAlterada(job_id=job_id, etapa=falha.etapa, status="erro")
            )
            raise
        return None

    async def _retomar(
        self,
        job_id: UUID,
        mensagem: SimulacaoConcluida,
        sessoes: async_sessionmaker[AsyncSession],
        producers: Producers,
        assentados: set[str],
    ) -> None:
        """Entrega o resultado do worker ao `interrupt()` pendente do ciclo que o pediu."""
        try:
            regra_id = await buscar_regra_do_resultado(sessoes, job_id, mensagem.resultado_id)
        except ResultadoDesconhecidoError as erro:
            raise JobDesconhecidoError(str(job_id)) from erro

        thread = thread_do_ciclo(job_id, regra_id)
        try:
            desfecho = await resume_to_completion(
                thread,
                _valor_da_retomada(mensagem),
                sessoes=sessoes,
                producers=producers,
            )
        except FalhaDoJobError:
            # A mensagem é rejeitada sem reentrega, e nada mais retoma este ciclo.
            assentados.add(thread)
            raise
        if desfecho is ResumeOutcome.NO_CHECKPOINT:
            raise JobDesconhecidoError(str(job_id))
        if desfecho is ResumeOutcome.NOT_PAUSED_YET:
            raise RetomadaIndisponivelError(str(job_id))
        # RESUMED e ALREADY_FINISHED terminam igual: a reentrega de um resultado já consumido
        # não retoma nada de novo, e confirmar a mensagem é o que tira a duplicata da fila.


def _recusar_se_encerrado(
    job_id: UUID,
    mensagem: RegraSubmetida | ParametrosConfirmados | SimulacaoConcluida,
    encerramento: EstadoDoEncerramento | None,
) -> None:
    """Depois da limpeza, nada do job roda; antes dela, só um resultado ainda esperado."""
    if encerramento is EstadoDoEncerramento.LIMPO:
        raise JobEncerradoError(str(job_id))
    if encerramento is EstadoDoEncerramento.REGISTRADO and isinstance(
        mensagem, RegraSubmetida | ParametrosConfirmados
    ):
        raise JobEncerradoError(str(job_id))


def thread_do_ciclo(job_id: UUID, regra_id: UUID | None) -> str:
    """Identifica o ciclo do grafo, que é por versão de regra e não por job.

    Um job que adapta a regra roda o pipeline de novo para a versão nova, e a thread do
    ciclo anterior já terminou: reaproveitá-la faria o LangGraph continuar de um
    checkpoint concluído em vez de começar o ciclo novo. Sem versão de regra ainda não há
    ciclo próprio, e o job responde por ele.
    """
    return f"{job_id}:{regra_id}" if regra_id is not None else str(job_id)


def _valor_da_retomada(mensagem: SimulacaoConcluida) -> dict[str, str | None]:
    """Só referências e campos de controle: os números ficam em `resultados_simulacao`."""
    return {
        "resultado_id": str(mensagem.resultado_id),
        "status": mensagem.status.value,
        "veredito": mensagem.veredito.value if mensagem.veredito is not None else None,
    }


def _estado_inicial(mensagem: RegraSubmetida) -> AgentState:
    estado: AgentState = {
        "job_id": str(mensagem.job_id),
        "origem": mensagem.origem.value,
        "competencias": list(mensagem.competencias),
    }
    if mensagem.regra_id is not None:
        estado["regra_id"] = str(mensagem.regra_id)
    if mensagem.submissao_id is not None:
        estado["submissao_id"] = str(mensagem.submissao_id)
    if mensagem.orcamento is not None:
        estado["orcamento"] = str(mensagem.orcamento)
    return estado


def _estado_confirmado(mensagem: ParametrosConfirmados) -> AgentState:
    if mensagem.competencias is None:
        raise ContextoAusenteError("contexto_ausente")
    estado: AgentState = {
        "job_id": str(mensagem.job_id),
        "regra_id": str(mensagem.regra_id),
        "competencias": list(mensagem.competencias),
    }
    if mensagem.orcamento is not None:
        estado["orcamento"] = str(mensagem.orcamento)
    return estado
