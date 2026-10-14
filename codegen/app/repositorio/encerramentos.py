"""O registro dos jobs encerrados, em `jobs_grafo_encerrados` (T-207).

A tabela é criada pela `api` (changeset `017-cria-jobs-grafo-encerrados.sql`), e o codegen tem
`SELECT`, `INSERT` e `UPDATE` só em `limpo_em`: registra o encerramento que a `api` anunciou e
marca quando os checkpoints do job foram removidos, sem reescrever o encerramento nem apagar a
linha. É essa linha que, depois da limpeza, diz que uma mensagem antiga é de um job encerrado, e
não de um job que este serviço não conhece.

O advisory lock por job coordena a limpeza com o processamento das mensagens do mesmo job: quem
processa segura o lock compartilhado, e quem limpa precisa do exclusivo. Os dois são de
transação, então nunca sobram numa conexão devolvida ao pool, e valem entre instâncias.
"""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contratos.mensagens import JobEncerrado


class EstadoDoEncerramento(StrEnum):
    """Um job sem linha não está encerrado: segue retomável pelo tempo que precisar."""

    REGISTRADO = "registrado"
    LIMPO = "limpo"


class JobInexistenteError(Exception):
    """O encerramento é de um job que não existe em `jobs`: repetir não o faz existir."""


_REGISTRAR = text(
    "INSERT INTO jobs_grafo_encerrados (job_id, evento_id, status, encerrado_em)"
    " VALUES (:job_id, :evento_id, :status, :encerrado_em)"
    " ON CONFLICT (job_id) DO NOTHING"
    " RETURNING id"
)
_ESTADO = text("SELECT limpo_em FROM jobs_grafo_encerrados WHERE job_id = :job_id")
_MARCAR_LIMPO = text(
    "UPDATE jobs_grafo_encerrados SET limpo_em = now()"
    " WHERE job_id = :job_id AND limpo_em IS NULL"
)
_PENDENTES = text(
    "SELECT job_id FROM jobs_grafo_encerrados WHERE limpo_em IS NULL ORDER BY encerrado_em, job_id"
)
_TRAVAR_COMPARTILHADO = text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:chave, 0))")
_TENTAR_TRAVAR_EXCLUSIVO = text("SELECT pg_try_advisory_xact_lock(hashtextextended(:chave, 0))")


def _chave(job_id: UUID) -> dict[str, str]:
    return {"chave": f"synapse.codegen.job:{job_id}"}


async def registrar(sessoes: async_sessionmaker[AsyncSession], evento: JobEncerrado) -> bool:
    """Grava o encerramento e devolve se ele é novo. Uma reentrega não muda a linha existente."""
    parametros = {
        "job_id": evento.job_id,
        "evento_id": evento.evento_id,
        "status": evento.status.value,
        "encerrado_em": evento.encerrado_em,
    }
    try:
        async with sessoes() as sessao, sessao.begin():
            resultado = await sessao.execute(_REGISTRAR, parametros)
            return resultado.scalar_one_or_none() is not None
    except IntegrityError as erro:
        # A única restrição que o `INSERT` pode violar é a chave estrangeira para `jobs`.
        raise JobInexistenteError(str(evento.job_id)) from erro


async def estado(sessao: AsyncSession, job_id: UUID) -> EstadoDoEncerramento | None:
    resultado = await sessao.execute(_ESTADO, {"job_id": job_id})
    linha = resultado.one_or_none()
    if linha is None:
        return None
    return (
        EstadoDoEncerramento.LIMPO
        if linha.limpo_em is not None
        else EstadoDoEncerramento.REGISTRADO
    )


async def foi_encerrado(sessoes: async_sessionmaker[AsyncSession], job_id: UUID) -> bool:
    """Lê o registro de encerramento numa sessão curta, fora do lock do processamento."""
    async with sessoes() as sessao:
        return await estado(sessao, job_id) is not None


async def marcar_limpo(sessao: AsyncSession, job_id: UUID) -> None:
    await sessao.execute(_MARCAR_LIMPO, {"job_id": job_id})


async def pendentes(sessoes: async_sessionmaker[AsyncSession]) -> list[UUID]:
    """Os jobs encerrados cuja limpeza ainda não terminou."""
    async with sessoes() as sessao:
        resultado = await sessao.execute(_PENDENTES)
        return [UUID(str(job_id)) for job_id in resultado.scalars()]


async def travar_compartilhado(sessao: AsyncSession, job_id: UUID) -> None:
    """Espera enquanto uma limpeza do job estiver em curso; libera no fim da transação."""
    await sessao.execute(_TRAVAR_COMPARTILHADO, _chave(job_id))


async def tentar_travar_exclusivo(sessao: AsyncSession, job_id: UUID) -> bool:
    """Falso quando alguma mensagem do job está sendo processada; não espera."""
    resultado = await sessao.execute(_TENTAR_TRAVAR_EXCLUSIVO, _chave(job_id))
    return bool(resultado.scalar_one())
