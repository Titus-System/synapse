"""`dispatch_execution` node: hands the recorded code to the worker.

Kept apart from `await_execution`: the paused node re-runs from its first line on resume, and
publishing there would send the command again on every resume.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import (
    ConclusaoDaTrilha,
    EtapaAlterada,
    ExecutarCodigo,
    NoConcluido,
    NoGrafo,
)
from app.core.logger import get_logger
from app.falhas import FalhaDoJobError
from app.graph.core.state import AgentState
from app.repositorio.artefatos import id_do_evento_de_trilha

logger = get_logger("app.graph.nodes.dispatch_execution")

# Etapa deste nó no vocabulário de `etapa-alterada`. `iniciada` aqui é o que move o job de
# `gerando_regra` para `simulando` na `api`.
ETAPA: NoGrafo = "delegacao_worker"

# O que este nó concluiu, em texto legível por pessoa (US04). Descreve a entrega do
# comando, não o código: o evento leva referências, nunca artefato (ADR-001).
RESUMO_DA_TRILHA = (
    "Execução delegada ao worker: o comando leva a referência do código gravado e as "
    "competências do período."
)


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
    codigo_gerado_id = UUID(state["codigo_gerado_id"])
    comando = ExecutarCodigo(
        job_id=job_id,
        codigo_gerado_id=codigo_gerado_id,
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

    # Por último, porque o nó conclui quando o comando foi entregue: anunciar a conclusão
    # antes seria afirmar algo que ainda pode falhar. Alarga a janela em que uma falha faz o
    # nó reexecutar e republicar o comando, mas o worker descarta comando repetido pelo
    # `codigo_gerado_id` já gravado.
    #
    # Sem `codigo_gerado_id` nem `prompt_id`: o schema os reserva ao nó que gerou o código e
    # aos que chamam modelo, e este não é nem um nem outro.
    await producers.no_concluido(
        NoConcluido(
            evento_id=id_do_evento_de_trilha(job_id, ETAPA, codigo_gerado_id),
            job_id=job_id,
            no=ETAPA,
            concluido_em=datetime.now(UTC),
            conclusao=ConclusaoDaTrilha(resumo=RESUMO_DA_TRILHA),
            regra_id=UUID(state["regra_id"]),
        )
    )
    logger.info("node conclusion published", extra={"no": ETAPA})
    return {}
