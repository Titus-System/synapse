"""Indisponibilidade do provedor de LLM: classificação da falha e espera limitada (T-268).

Sem isto, um 503 ou um timeout subia como falha transitória e o broker reentregava a mensagem na
hora, sem espera nem limite (DEC-089). Aqui a espera acontece dentro do processamento da mensagem,
antes do `ack`: a primeira falha avisa a `api`, as novas tentativas esperam 30, 60 e 120 segundos
(e 120 depois disso) e a janela de 10 minutos, contada da primeira falha, encerra o job em erro.
A janela fica abaixo do `consumer_timeout` padrão do RabbitMQ, de 30 minutos.

A mensagem da exceção do provedor nunca vai para log, evento ou métrica: a classificação decide só
por tipo e código, e a falha final é lançada sem a causa encadeada.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Final
from uuid import UUID

from httpx import NetworkError, TimeoutException
from langchain_core.runnables import RunnableConfig

from app.contratos.mensagens import EtapaAlterada, NoGrafo
from app.core.logger import get_logger
from app.core.metrics.global_metrics import espera_do_provedor, falhas_do_provedor
from app.falhas import ProvedorIndisponivelError
from app.graph.core.state import AgentState
from app.repositorio import encerramentos

logger = get_logger("app.graph.core.llm.disponibilidade")

CAUSA: Final = "provedor_indisponivel"

# 429, 500, 502, 503 e 504. 400, 401, 403 e 404 são configuração ou requisição inválida e
# continuam com o tratamento atual.
CODIGOS_HTTP_INDISPONIVEIS: Final = frozenset({429, 500, 502, 503, 504})

ESPERAS_S: Final = (30.0, 60.0, 120.0)
JANELA_S: Final = 600.0


class JobEncerradoDuranteEsperaError(Exception):
    """O usuário cancelou ou arquivou o job enquanto o codegen esperava o provedor."""


def e_indisponibilidade_do_provedor(erro: BaseException) -> bool:
    """Diz se a falha da chamada ao modelo é do provedor, inclusive embrulhada.

    O `langchain_google_genai` relança o erro do `google.genai` com `raise ... from`, então a
    cadeia de causas é percorrida inteira.
    """
    visitados: set[int] = set()
    atual: BaseException | None = erro
    while atual is not None and id(atual) not in visitados:
        visitados.add(id(atual))
        if _erro_de_provedor(atual):
            return True
        atual = atual.__cause__ or atual.__context__
    return False


def _erro_de_provedor(erro: BaseException) -> bool:
    if isinstance(erro, TimeoutError | ConnectionError | TimeoutException | NetworkError):
        return True
    # `google.genai.errors.APIError` e as classes do langchain que a embrulham trazem o código.
    codigo = getattr(erro, "code", None)
    return isinstance(codigo, int) and codigo in CODIGOS_HTTP_INDISPONIVEIS


def espera_da_tentativa(tentativa: int) -> float:
    return ESPERAS_S[min(tentativa, len(ESPERAS_S) - 1)]


async def _dormir(segundos: float) -> None:
    await asyncio.sleep(segundos)


def _agora() -> float:
    return time.monotonic()


def ganchos_da_espera(
    config: RunnableConfig, state: AgentState, no: NoGrafo
) -> tuple[Callable[[], Awaitable[None]], Callable[[], Awaitable[bool]]]:
    """O aviso à `api` e a consulta de encerramento do nó, lidos de `config` e `state` ao usar.

    Sem falha de provedor nada disso é tocado, então um nó que não espera não passa a exigir
    `producers`, `sessoes` nem `job_id`.
    """

    async def avisar() -> None:
        producers = config["configurable"]["producers"]
        await producers.etapa_alterada(
            EtapaAlterada(job_id=UUID(state["job_id"]), etapa=no, status="aguardando_provedor")
        )

    async def encerrado() -> bool:
        return await encerramentos.foi_encerrado(
            config["configurable"]["sessoes"], UUID(state["job_id"])
        )

    return avisar, encerrado


async def chamar_com_espera_do_provedor[T](
    chamada: Callable[[], Awaitable[T]],
    *,
    no: NoGrafo,
    esgotada: type[ProvedorIndisponivelError],
    avisar: Callable[[], Awaitable[None]],
    encerrado: Callable[[], Awaitable[bool]],
    sleep: Callable[[float], Awaitable[None]] | None = None,
    agora: Callable[[], float] | None = None,
) -> T:
    """Executa `chamada` e, se o provedor estiver indisponível, espera e tenta de novo.

    Uma falha que não é do provedor sobe como veio. `avisar` roda uma única vez, na primeira
    falha da chamada; uma falha dele sobe como transitória e a reentrega tenta de novo. Antes de
    cada nova tentativa `encerrado` é consultado, e o job encerrado lança
    `JobEncerradoDuranteEsperaError`. Esgotada a janela, lança `esgotada`.

    As métricas contam chamadas que tiveram falha de provedor, uma por desfecho, e não cada
    tentativa. O tempo de espera vai para o histograma em qualquer fim da espera.
    """
    dormir = sleep or _dormir
    relogio = agora or _agora
    primeira_falha: float | None = None
    tentativa = 0
    try:
        while True:
            indisponivel = False
            try:
                resultado = await chamada()
            except Exception as erro:
                if not e_indisponibilidade_do_provedor(erro):
                    raise
                indisponivel = True
            if not indisponivel:
                if primeira_falha is not None:
                    falhas_do_provedor.labels(no=no, desfecho="recuperado").inc()
                    logger.info(
                        "provider recovered",
                        extra={"causa": CAUSA, "tentativas": tentativa},
                    )
                return resultado

            # Fora do `except`: a falha final não carrega a exceção do provedor em __context__.
            if primeira_falha is None:
                primeira_falha = relogio()
                logger.warning("provider unavailable, waiting to retry", extra={"causa": CAUSA})
                await avisar()
            espera = espera_da_tentativa(tentativa)
            if relogio() - primeira_falha + espera > JANELA_S:
                falhas_do_provedor.labels(no=no, desfecho="esgotado").inc()
                logger.error(
                    "provider unavailable, retry window exhausted",
                    extra={"causa": CAUSA, "tentativas": tentativa},
                )
                raise esgotada("Provider unavailable for the whole retry window")
            logger.warning(
                "provider unavailable, retrying after wait",
                extra={"causa": CAUSA, "tentativa": tentativa + 1, "espera_s": espera},
            )
            await dormir(espera)
            tentativa += 1
            if await encerrado():
                logger.info("job closed while waiting for the provider", extra={"causa": CAUSA})
                raise JobEncerradoDuranteEsperaError
    finally:
        if primeira_falha is not None:
            espera_do_provedor.labels(no=no).observe(relogio() - primeira_falha)
