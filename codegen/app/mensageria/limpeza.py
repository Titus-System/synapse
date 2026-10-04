"""Limpeza dos checkpoints de jobs encerrados (T-207).

O fato que autoriza a limpeza é o `job-encerrado` da `api`, e nunca a conclusão de um ciclo do
grafo: um job que espera correção, confirmação, resultado ou decisão do usuário continua
retomável pelo tempo que precisar. O encerramento é registrado em `jobs_grafo_encerrados` antes
de qualquer remoção, e é esse registro, e não o checkpoint, que depois reconhece uma mensagem
antiga do job.

A remoção espera o que ainda falta acontecer. Um ciclo pausado à espera do resultado, ou com uma
retomada que não terminou, fica até a mensagem dele ser processada: o encerramento pode chegar
antes do resultado, e os efeitos do resultado, como as publicações de auditoria, não podem se
perder. Quem processa uma mensagem do job segura o lock compartilhado e, ao terminar, tenta a
limpeza de novo. Uma limpeza interrompida é retomada na subida do serviço, pelas linhas com
`limpo_em` nulo, sem depender de uma nova entrega do evento.
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contratos.mensagens import JobEncerrado
from app.core.logger import get_logger, job_id_ctx
from app.core.metrics.global_metrics import limpeza_de_checkpoint_duracao, limpezas_de_checkpoint
from app.graph.entrypoint import apagar_ciclos, ciclos_do_job
from app.repositorio import encerramentos
from app.repositorio.encerramentos import EstadoDoEncerramento

logger = get_logger("app.mensageria.limpeza")


class ResultadoDaLimpeza(StrEnum):
    CONCLUIDA = "concluida"
    ADIADA = "adiada"
    FALHOU = "falhou"


@dataclass(frozen=True)
class _Tentativa:
    resultado: ResultadoDaLimpeza
    ciclos_removidos: int = 0
    ciclos_pendentes: int = 0
    motivo: str | None = None


class LimpezaDeCheckpoints:
    def __init__(self, sessoes: async_sessionmaker[AsyncSession]) -> None:
        self.sessoes = sessoes

    async def registrar(self, evento: JobEncerrado) -> None:
        """Registra o encerramento e tenta a limpeza.

        Uma falha ao registrar sobe: o fato ainda não está durável, e a reentrega do evento é o
        que o salva. Depois do registro, nenhuma falha da limpeza sobe, porque a retomada na
        subida a refaz a partir da linha gravada.
        """
        novo = await encerramentos.registrar(self.sessoes, evento)
        logger.info(
            "encerramento do job registrado",
            extra={
                "evento_id": str(evento.evento_id),
                "status": evento.status.value,
                "ja_registrado": not novo,
            },
        )
        await self.limpar(evento.job_id)

    @asynccontextmanager
    async def durante_o_processamento(
        self, job_id: UUID
    ) -> AsyncIterator[EstadoDoEncerramento | None]:
        """Segura o lock compartilhado do job enquanto uma mensagem dele é processada.

        Entrega o estado do encerramento lido sob o lock: uma limpeza que já terminou foi
        confirmada antes de o lock ser concedido, e nenhuma começa até o processamento acabar.
        """
        async with self.sessoes() as sessao, sessao.begin():
            await encerramentos.travar_compartilhado(sessao, job_id)
            yield await encerramentos.estado(sessao, job_id)

    async def limpar(
        self, job_id: UUID, liberados: frozenset[str] = frozenset()
    ) -> ResultadoDaLimpeza | None:
        """Remove os ciclos que podem ser descartados e marca a limpeza quando não resta nenhum.

        `liberados` são ciclos cuja mensagem já foi assentada sem que eles terminassem, como uma
        retomada que falhou de forma permanente: nada mais os retoma. Devolve `None` quando o job
        não está encerrado ou já foi limpo. Nunca levanta.
        """
        inicio = time.monotonic()
        try:
            tentativa = await self._tentar(job_id, liberados)
        except Exception as erro:
            # O texto da exceção pode carregar dados do banco ou do checkpoint; só a classe vai.
            tentativa = _Tentativa(ResultadoDaLimpeza.FALHOU, motivo=type(erro).__name__)
        if tentativa is None:
            return None

        resultado = tentativa.resultado
        limpezas_de_checkpoint.labels(resultado=resultado.value).inc()
        limpeza_de_checkpoint_duracao.labels(resultado=resultado.value).observe(
            time.monotonic() - inicio
        )
        if resultado is ResultadoDaLimpeza.CONCLUIDA:
            logger.info(
                "limpeza de checkpoints concluída",
                extra={"ciclos_removidos": tentativa.ciclos_removidos},
            )
        elif resultado is ResultadoDaLimpeza.ADIADA:
            logger.info(
                "limpeza de checkpoints adiada",
                extra={
                    "motivo": tentativa.motivo,
                    "ciclos_removidos": tentativa.ciclos_removidos,
                    "ciclos_pendentes": tentativa.ciclos_pendentes,
                },
            )
        else:
            logger.error("limpeza de checkpoints falhou", extra={"causa": tentativa.motivo})
        return resultado

    async def _tentar(self, job_id: UUID, liberados: frozenset[str]) -> _Tentativa | None:
        async with self.sessoes() as sessao, sessao.begin():
            if await encerramentos.estado(sessao, job_id) is not EstadoDoEncerramento.REGISTRADO:
                return None
            if not await encerramentos.tentar_travar_exclusivo(sessao, job_id):
                return _Tentativa(ResultadoDaLimpeza.ADIADA, motivo="processamento_em_andamento")
            # Outra limpeza pode ter terminado entre a leitura e o lock.
            if await encerramentos.estado(sessao, job_id) is not EstadoDoEncerramento.REGISTRADO:
                return None

            ciclos = await ciclos_do_job(job_id)
            descartaveis = [
                c.thread_id for c in ciclos if not c.pendente or c.thread_id in liberados
            ]
            pendentes = len(ciclos) - len(descartaveis)
            await apagar_ciclos(descartaveis)
            if pendentes:
                return _Tentativa(
                    ResultadoDaLimpeza.ADIADA,
                    ciclos_removidos=len(descartaveis),
                    ciclos_pendentes=pendentes,
                    motivo="ciclo_pendente",
                )
            # O lock exclusivo impede uma escrita nova; a conferência é o que permite afirmar que
            # nada sobrou antes de marcar.
            restantes = await ciclos_do_job(job_id)
            if restantes:
                return _Tentativa(
                    ResultadoDaLimpeza.ADIADA,
                    ciclos_removidos=len(descartaveis),
                    ciclos_pendentes=len(restantes),
                    motivo="ciclo_restante",
                )
            # `limpo_em` é confirmado antes de o lock ser solto, junto com o commit.
            await encerramentos.marcar_limpo(sessao, job_id)
            return _Tentativa(ResultadoDaLimpeza.CONCLUIDA, ciclos_removidos=len(descartaveis))

    async def retomar_pendentes(self) -> None:
        """Refaz as limpezas que não terminaram: as adiadas e as interrompidas por uma queda."""
        try:
            jobs = await encerramentos.pendentes(self.sessoes)
        except Exception as erro:
            logger.error(
                "retomada de limpezas pendentes falhou", extra={"causa": type(erro).__name__}
            )
            return
        logger.info("limpezas pendentes retomadas", extra={"quantidade": len(jobs)})
        for job_id in jobs:
            token = job_id_ctx.set(str(job_id))
            try:
                await self.limpar(job_id)
            finally:
                job_id_ctx.reset(token)
