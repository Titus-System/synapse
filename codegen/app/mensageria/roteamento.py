from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contratos.mensagens import ParametrosConfirmados, RegraSubmetida, SimulacaoConcluida
from app.graph.core.state import AgentState
from app.graph.entrypoint import run_to_completion
from app.mensageria.producers import Producers

type Entrada = RegraSubmetida | ParametrosConfirmados | SimulacaoConcluida


class JobDesconhecidoError(Exception):
    """O roteador não encontrou o grafo correspondente ao job recebido."""


class RoteadorGrafo(Protocol):
    async def entregar(self, job_id: UUID, mensagem: Entrada) -> None:
        """Retorna só após processamento persistido; reentregas devem ser idempotentes.

        Resolve/cria o grafo de regra-submetida e retoma os demais pelo job_id.
        Lança JobDesconhecidoError se não houver grafo correspondente à mensagem, e
        `app.repositorio.regras.RegraInvalidaError` se a regra referenciada não existir ou
        for inválida.
        """
        ...


@dataclass
class GraphRouter:
    """Concrete `RoteadorGrafo`: translates `RegraSubmetida` into the graph's initial state.

    `sessoes` and `producers` are set once by the app's lifespan, after the corresponding
    resource (database engine, broker connection) is ready - see `app/main.py`. Handling
    `ParametrosConfirmados`/`SimulacaoConcluida` (resuming a paused run) is out of scope here.
    """

    sessoes: async_sessionmaker[AsyncSession] | None = None
    producers: Producers | None = None

    async def entregar(self, job_id: UUID, mensagem: Entrada) -> None:
        if not isinstance(mensagem, RegraSubmetida):
            raise NotImplementedError("GraphRouter only handles regra-submetida for now")
        if self.sessoes is None or self.producers is None:
            raise RuntimeError("GraphRouter is not fully wired yet")

        await run_to_completion(
            str(job_id),
            _estado_inicial(mensagem),
            sessoes=self.sessoes,
            producers=self.producers,
        )


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
