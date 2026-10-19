"""Read-only access to the transcription; audio bytes never enter codegen."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.falhas import FalhaDoJobError


class TranscricaoIndisponivelError(FalhaDoJobError):
    etapa = "extracao_parametros"


async def buscar_transcricao(sessoes: async_sessionmaker[AsyncSession], submissao_id: UUID) -> str:
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            text("SELECT transcricao FROM submissoes WHERE id = :submissao_id"),
            {"submissao_id": submissao_id},
        )
        linha = resultado.mappings().one_or_none()
    transcricao = None if linha is None else linha["transcricao"]
    if not isinstance(transcricao, str) or not transcricao.strip():
        raise TranscricaoIndisponivelError("Transcription unavailable")
    return transcricao
