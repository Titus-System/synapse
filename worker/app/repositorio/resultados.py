"""Escrita e consulta de `resultados_simulacao` (T-067).

O worker só tem SELECT e INSERT nesta tabela, e nenhuma permissão em outra
(api/.../changesets/010-cria-resultados-simulacao.sql): uma linha gravada não se altera nem se
apaga. Por isso a consulta existe: um comando que volta depois de o resultado já ter sido
gravado não pode gravar uma segunda linha, e a primeira não teria como ser removida.
"""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# `criado_em` não tem default no banco. A escrita fica a cargo do chamador: confirmar antes de
# publicar é o que impede um evento de referenciar uma linha que não existe.
_INSERT = text(
    """
    INSERT INTO resultados_simulacao
        (job_id, codigo_gerado_id, status, totais, veredito, assercoes, decomposicao, criado_em)
    VALUES
        (:job_id, :codigo_gerado_id, :status, CAST(:totais AS jsonb), :veredito,
         CAST(:assercoes AS jsonb), CAST(:decomposicao AS jsonb), now())
    RETURNING id
    """
)

# `erro_infra` fica de fora: é o desfecho de um comando que esgotou as tentativas e foi para a
# DLQ, e um comando reenviado de lá pelo operador tem de executar de novo, não repetir o erro.
_CONSULTA = text(
    """
    SELECT id, job_id, status, veredito, totais
    FROM resultados_simulacao
    WHERE job_id = :job_id AND codigo_gerado_id = :codigo_gerado_id AND status <> 'erro_infra'
    ORDER BY criado_em, id
    LIMIT 1
    """
)


@dataclass(frozen=True)
class ResultadoGravado:
    """O que o evento precisa da linha: a referência, o desfecho e os agregados."""

    id: UUID
    job_id: UUID
    status: str
    veredito: str | None
    totais: dict[str, Any] | None


def _json(valor: object) -> str | None:
    """`NaN` e infinito não são JSON: o Postgres os recusaria, e um agregado não finito não
    deveria ter chegado até aqui."""
    return None if valor is None else json.dumps(valor, ensure_ascii=False, allow_nan=False)


async def gravar_resultado(
    sessao: AsyncSession,
    *,
    job_id: UUID,
    codigo_gerado_id: UUID,
    status: str,
    veredito: str | None,
    totais: dict[str, Any] | None,
    assercoes: list[Any],
    decomposicao: dict[str, Any] | None,
) -> ResultadoGravado:
    """Insere a linha. Quem chama abre a transação e a confirma antes de publicar."""
    resultado = await sessao.execute(
        _INSERT,
        {
            "job_id": job_id,
            "codigo_gerado_id": codigo_gerado_id,
            "status": status,
            "totais": _json(totais),
            "veredito": veredito,
            "assercoes": _json(assercoes),
            "decomposicao": _json(decomposicao),
        },
    )
    return ResultadoGravado(
        id=resultado.scalar_one(),
        job_id=job_id,
        status=status,
        veredito=veredito,
        totais=totais,
    )


async def buscar_resultado(
    sessao: AsyncSession, job_id: UUID, codigo_gerado_id: UUID
) -> ResultadoGravado | None:
    """A linha já gravada para este código neste job, se houver (ignora `erro_infra`)."""
    resultado = await sessao.execute(
        _CONSULTA, {"job_id": job_id, "codigo_gerado_id": codigo_gerado_id}
    )
    linha = resultado.mappings().first()
    if linha is None:
        return None
    totais = linha["totais"]
    return ResultadoGravado(
        id=linha["id"],
        job_id=linha["job_id"],
        status=linha["status"],
        veredito=linha["veredito"],
        totais=json.loads(totais) if isinstance(totais, str) else totais,
    )
