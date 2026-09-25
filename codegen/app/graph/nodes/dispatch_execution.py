"""`dispatch_execution` node: hands the recorded code to the worker.

Kept apart from `await_execution`: the paused node re-runs from its first line on resume, and
publishing there would send the command again on every resume.
"""

from decimal import Decimal
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import EtapaAlterada, ExecutarCodigo, NoGrafo
from app.core.logger import get_logger
from app.falhas import FalhaDoJobError
from app.graph.core.state import AgentState

logger = get_logger("app.graph.nodes.dispatch_execution")

# Etapa deste nó no vocabulário de `etapa-alterada`. `iniciada` aqui é o que move o job de
# `gerando_regra` para `simulando` na `api`.
ETAPA: NoGrafo = "delegacao_worker"


class OrcamentoAusenteError(FalhaDoJobError):
    """The job has no `orcamento`, which `executar-codigo` requires.

    The event carries it as an optional field, and its absence is never read as zero: the
    budget is an input to the worker's verdict, not something this service may invent.
    """

    etapa = ETAPA


async def dispatch_execution(state: AgentState, config: RunnableConfig) -> AgentState:
    """Publish the command with a reference to the recorded code, never the code itself."""
    orcamento = state.get("orcamento")
    if orcamento is None:
        raise OrcamentoAusenteError("executar-codigo requires the job's orcamento")

    job_id = UUID(state["job_id"])
    comando = ExecutarCodigo(
        job_id=job_id,
        codigo_gerado_id=UUID(state["codigo_gerado_id"]),
        competencias=list(state["competencias"]),
        orcamento=Decimal(orcamento),
    )
    producers = config["configurable"]["producers"]

    # `etapa-alterada` primeiro, e a ordem importa. Do lado da `api` ele é idempotente (a
    # transição só vale a partir de `gerando_regra`, então uma segunda cópia não faz nada),
    # enquanto `executar-codigo` não é: se este nó rodar de novo, republica o comando. Com o
    # idempotente na frente, uma reexecução arrisca duplicar só o comando, e o job já está em
    # `simulando` antes de o worker poder concluir - senão `simulacao-concluida` chegaria com
    # o job ainda em `gerando_regra`, transição que a `api` recusa em silêncio.
    await producers.etapa_alterada(EtapaAlterada(job_id=job_id, etapa=ETAPA, status="iniciada"))
    await producers.executar_codigo(comando)
    logger.info(
        "execution command published", extra={"codigo_gerado_id": state["codigo_gerado_id"]}
    )
    return {}
