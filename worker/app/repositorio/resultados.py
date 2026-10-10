"""Escrita e consulta de `resultados_simulacao` (T-067).

O worker só tem SELECT e INSERT nesta tabela, e nenhuma permissão em outra
(api/.../changesets/010-cria-resultados-simulacao.sql): uma linha gravada não se altera nem se
apaga. Por isso a consulta existe: um comando que volta depois de o resultado já ter sido
gravado não pode gravar uma segunda linha, e a primeira não teria como ser removida.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# `criado_em` não tem default no banco. A escrita fica a cargo do chamador: confirmar antes de
# publicar é o que impede um evento de referenciar uma linha que não existe. O diagnóstico vai no
# mesmo INSERT porque o worker não tem UPDATE: depois de gravada, a linha não o recebe mais.
_INSERT = text(
    """
    INSERT INTO resultados_simulacao
        (job_id, codigo_gerado_id, status, totais, veredito, assercoes, decomposicao,
         diagnostico, meta_venda, proposito, criado_em)
    VALUES
        (:job_id, :codigo_gerado_id, :status, CAST(:totais AS jsonb), :veredito,
         CAST(:assercoes AS jsonb), CAST(:decomposicao AS jsonb), CAST(:diagnostico AS jsonb),
         CAST(:meta_venda AS numeric), :proposito, now())
    RETURNING id
    """
)

# `erro_infra` fica de fora: é o desfecho de um comando que esgotou as tentativas e foi para a
# DLQ, e um comando reenviado de lá pelo operador tem de executar de novo, não repetir o erro.
# A meta e o propósito fazem parte de "o mesmo comando" (T-270): a busca da meta maior roda o
# mesmo código em várias metas candidatas, e cada candidata é uma execução própria.
_CONSULTA = text(
    """
    SELECT id, job_id, status, veredito, totais, meta_venda, proposito
    FROM resultados_simulacao
    WHERE job_id = :job_id AND codigo_gerado_id = :codigo_gerado_id AND status <> 'erro_infra'
      AND proposito = :proposito
      AND meta_venda IS NOT DISTINCT FROM CAST(:meta_venda AS numeric)
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
    # A meta em que a execução foi simulada, None sobre as vendas históricas (T-270).
    meta_venda: float | None = None
    proposito: str = "simulacao"


def _json(valor: object) -> str | None:
    """`NaN` e infinito não são JSON: o Postgres os recusaria, e um agregado não finito não
    deveria ter chegado até aqui."""
    return None if valor is None else json.dumps(valor, ensure_ascii=False, allow_nan=False)


def _numeric(meta_venda: float | None) -> Decimal | None:
    """A meta como o comando a trouxe, pela representação do número: lida de volta, a coluna
    `numeric` devolve o mesmo float, e a consulta da reentrega a encontra por igualdade."""
    return None if meta_venda is None else Decimal(str(meta_venda))


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
    diagnostico: Mapping[str, object] | None,
    meta_venda: float | None,
    proposito: str,
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
            "diagnostico": _json(diagnostico),
            "meta_venda": _numeric(meta_venda),
            "proposito": proposito,
        },
    )
    return ResultadoGravado(
        id=resultado.scalar_one(),
        job_id=job_id,
        status=status,
        veredito=veredito,
        totais=totais,
        meta_venda=meta_venda,
        proposito=proposito,
    )


async def buscar_resultado(
    sessao: AsyncSession,
    job_id: UUID,
    codigo_gerado_id: UUID,
    *,
    meta_venda: float | None,
    proposito: str,
) -> ResultadoGravado | None:
    """A linha já gravada para este código neste job, nesta meta e com este propósito, se houver
    (ignora `erro_infra`)."""
    resultado = await sessao.execute(
        _CONSULTA,
        {
            "job_id": job_id,
            "codigo_gerado_id": codigo_gerado_id,
            "meta_venda": _numeric(meta_venda),
            "proposito": proposito,
        },
    )
    linha = resultado.mappings().first()
    if linha is None:
        return None
    totais = linha["totais"]
    meta = linha["meta_venda"]
    return ResultadoGravado(
        id=linha["id"],
        job_id=linha["job_id"],
        status=linha["status"],
        veredito=linha["veredito"],
        totais=json.loads(totais) if isinstance(totais, str) else totais,
        meta_venda=None if meta is None else float(meta),
        proposito=linha["proposito"],
    )
