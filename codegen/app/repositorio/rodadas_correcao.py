"""Histórico de correções por cadeia, consultado somente com SELECT (T-224)."""

from dataclasses import dataclass
from uuid import UUID

import simplejson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Limita o contexto do modelo, nunca a quantidade de correções que o usuário pode enviar.
LIMITE_HISTORICO_CORRECOES = 5


@dataclass(frozen=True, slots=True, repr=False)
class CorrecaoAnterior:
    conflitos: list[dict[str, object]]
    texto: str


async def buscar_historico_correcao(
    sessoes: async_sessionmaker[AsyncSession], job_id: UUID, submissao_id: UUID
) -> list[CorrecaoAnterior]:
    """Parte da rodada da submissão atual e percorre até cinco ancestrais do mesmo job.

    O índice da submissão atual é só a âncora: ela não entra no histórico. O SQL traz as
    rodadas anteriores, inclusive as que falharam, em ordem cronológica dentro do limite.
    Ausência da âncora, como na primeira correção, devolve uma lista vazia.
    """
    consulta = text(
        "WITH RECURSIVE cadeia AS ("
        " SELECT id, rodada_anterior_id, 0 AS profundidade FROM rodadas_correcao"
        " WHERE job_id = :job_id AND submissao_correcao_id = :submissao_id"
        " UNION ALL"
        " SELECT anterior.id, anterior.rodada_anterior_id, cadeia.profundidade + 1"
        " FROM rodadas_correcao anterior"
        " JOIN cadeia ON anterior.id = cadeia.rodada_anterior_id"
        " WHERE anterior.job_id = :job_id AND cadeia.profundidade < :limite"
        ")"
        " SELECT r.conflitos::text AS conflitos, s.transcricao AS texto"
        " FROM cadeia JOIN rodadas_correcao r ON r.id = cadeia.id AND r.job_id = :job_id"
        " LEFT JOIN submissoes s ON s.id = r.submissao_correcao_id"
        " WHERE cadeia.profundidade > 0 ORDER BY cadeia.profundidade DESC"
    )
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            consulta,
            {
                "job_id": str(job_id),
                "submissao_id": str(submissao_id),
                "limite": LIMITE_HISTORICO_CORRECOES,
            },
        )
        linhas = resultado.mappings().all()

    historico: list[CorrecaoAnterior] = []
    for linha in linhas:
        # Uma rodada ainda pendente não é uma correção anterior; não tem texto enviado.
        if not isinstance(linha["texto"], str) or not linha["texto"].strip():
            continue
        conflitos = simplejson.loads(linha["conflitos"])
        historico.append(CorrecaoAnterior(conflitos=conflitos, texto=linha["texto"]))
    return historico
