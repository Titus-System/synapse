from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contratos.mensagens import (
    EtapaAlterada,
    ParametrosConfirmados,
    RegraSubmetida,
    SimulacaoConcluida,
)
from app.falhas import FalhaDoJobError
from app.graph.core.state import AgentState
from app.graph.entrypoint import ResumeOutcome, resume_to_completion, run_to_completion
from app.mensageria.producers import Producers
from app.repositorio.resultados import ResultadoDesconhecidoError, buscar_regra_do_resultado

type Entrada = RegraSubmetida | ParametrosConfirmados | SimulacaoConcluida


class JobDesconhecidoError(Exception):
    """O roteador não encontrou o grafo correspondente ao job recebido."""


class RetomadaIndisponivelError(Exception):
    """O grafo existe mas ainda não chegou à pausa: a reentrega do broker é a resposta certa.

    O worker pode publicar o resultado antes de o checkpoint com o `interrupt()` pendente ser
    gravado. Rejeitar a mensagem aqui perderia o resultado de uma simulação que aconteceu.
    """


class RoteadorGrafo(Protocol):
    async def entregar(self, job_id: UUID, mensagem: Entrada) -> None:
        """Retorna só após processamento persistido; reentregas devem ser idempotentes.

        Resolve/cria o grafo de regra-submetida e retoma os demais pelo job_id.
        Lança JobDesconhecidoError se não houver grafo correspondente à mensagem,
        RetomadaIndisponivelError quando o grafo ainda não chegou à pausa, e
        `app.falhas.FalhaDoJobError` quando o processamento falha de forma permanente - depois de
        avisar a `api`, para que o job termine em erro em vez de ficar pendurado.
        """
        ...


@dataclass
class GraphRouter:
    """Concrete `RoteadorGrafo`: translates `RegraSubmetida` into the graph's initial state.

    `sessoes` and `producers` are set once by the app's lifespan, after the corresponding
    resource (database engine, broker connection) is ready - see `app/main.py`. Handling
    `ParametrosConfirmados` (resuming after the user confirms the parameters) is out of scope
    here.
    """

    sessoes: async_sessionmaker[AsyncSession] | None = None
    producers: Producers | None = None

    async def entregar(self, job_id: UUID, mensagem: Entrada) -> None:
        if self.sessoes is None or self.producers is None:
            raise RuntimeError("GraphRouter is not fully wired yet")

        if isinstance(mensagem, ParametrosConfirmados):
            # Falta o que o ciclo novo precisa e o evento não carrega: `competencias` e
            # `orcamento` estão em `jobs`, tabela em que o codegen não tem permissão.
            raise NotImplementedError("GraphRouter does not handle parametros-confirmados yet")

        try:
            if isinstance(mensagem, SimulacaoConcluida):
                await self._retomar(job_id, mensagem, self.sessoes, self.producers)
            else:
                await run_to_completion(
                    thread_do_ciclo(job_id, mensagem.regra_id),
                    _estado_inicial(mensagem),
                    sessoes=self.sessoes,
                    producers=self.producers,
                )
        except FalhaDoJobError as falha:
            # Esta é a fronteira que sabe que o job acabou: sem este aviso, a `api` deixaria
            # o job em `gerando_regra` para sempre. Uma falha ao publicar não é tratada de
            # propósito - ela sobe como falha comum, o consumer reenfileira e a reentrega
            # tenta avisar de novo. Melhor do que engolir o aviso.
            await self.producers.etapa_alterada(
                EtapaAlterada(job_id=job_id, etapa=falha.etapa, status="erro")
            )
            raise

    async def _retomar(
        self,
        job_id: UUID,
        mensagem: SimulacaoConcluida,
        sessoes: async_sessionmaker[AsyncSession],
        producers: Producers,
    ) -> None:
        """Entrega o resultado do worker ao `interrupt()` pendente do ciclo que o pediu."""
        try:
            regra_id = await buscar_regra_do_resultado(sessoes, job_id, mensagem.resultado_id)
        except ResultadoDesconhecidoError as erro:
            raise JobDesconhecidoError(str(job_id)) from erro

        desfecho = await resume_to_completion(
            thread_do_ciclo(job_id, regra_id),
            _valor_da_retomada(mensagem),
            sessoes=sessoes,
            producers=producers,
        )
        if desfecho is ResumeOutcome.NO_CHECKPOINT:
            raise JobDesconhecidoError(str(job_id))
        if desfecho is ResumeOutcome.NOT_PAUSED_YET:
            raise RetomadaIndisponivelError(str(job_id))
        # RESUMED e ALREADY_FINISHED terminam igual: a reentrega de um resultado já consumido
        # não retoma nada de novo, e confirmar a mensagem é o que tira a duplicata da fila.


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
    if mensagem.orcamento is not None:
        estado["orcamento"] = str(mensagem.orcamento)
    return estado
