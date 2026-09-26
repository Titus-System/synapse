"""Leitura do código gerado pelo codegen.

O worker só tem SELECT em codigos_gerados (GRANT em
api/.../changesets/009-cria-codigos-gerados.sql).
"""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_QUERY = text(
    "SELECT id, job_id, linguagem, fonte FROM codigos_gerados WHERE id = :codigo_gerado_id"
)


class CodigoNaoEncontradoError(Exception):
    """`codigo_gerado_id` do comando não existe em `codigos_gerados`."""

    def __init__(self, codigo_gerado_id: UUID) -> None:
        self.codigo_gerado_id = codigo_gerado_id
        super().__init__(f"código gerado não encontrado: {codigo_gerado_id}")


class CodigoGerado(BaseModel):
    id: UUID
    job_id: UUID
    linguagem: str
    fonte: str


async def buscar_codigo(sessao: AsyncSession, codigo_gerado_id: UUID) -> CodigoGerado:
    resultado = await sessao.execute(_QUERY, {"codigo_gerado_id": codigo_gerado_id})
    linha = resultado.mappings().first()
    if linha is None:
        raise CodigoNaoEncontradoError(codigo_gerado_id)

    return CodigoGerado.model_validate(dict(linha))
