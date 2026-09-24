"""`dispatch_execution` node: publishes `executar-codigo` for the worker.

Kept apart from `await_execution`: the paused node re-runs from its first line on resume, and
publishing there would send the command again on every resume.
"""

from decimal import Decimal
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import ExecutarCodigo
from app.core.logger import get_logger
from app.graph.core.state import AgentState

logger = get_logger("app.graph.nodes.dispatch_execution")


class OrcamentoAusenteError(Exception):
    """The job has no `orcamento`, which `executar-codigo` requires."""


async def dispatch_execution(state: AgentState, config: RunnableConfig) -> AgentState:
    """Publish the command with a reference to the recorded code, never the code itself."""
    orcamento = state.get("orcamento")
    if orcamento is None:
        raise OrcamentoAusenteError("executar-codigo requires the job's orcamento")

    comando = ExecutarCodigo(
        job_id=UUID(state["job_id"]),
        codigo_gerado_id=UUID(state["codigo_gerado_id"]),
        competencias=list(state["competencias"]),
        orcamento=Decimal(orcamento),
    )
    producers = config["configurable"]["producers"]
    await producers.executar_codigo(comando)
    logger.info(
        "execution command published", extra={"codigo_gerado_id": state["codigo_gerado_id"]}
    )
    return {}
