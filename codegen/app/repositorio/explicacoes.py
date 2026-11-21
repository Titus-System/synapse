"""Leitura e gravação de `explicacoes`, a narrativa de cada simulação com sucesso.

O codegen só tem `SELECT` e `INSERT` na tabela (changeset 011): uma linha não é corrigida, e o
`ON CONFLICT DO NOTHING` sobre o id derivado do resultado faz a reexecução do nó não gravar nada
de novo. O prompt e a resposta que originaram o texto entram na mesma transação, para que a
linha nunca exista sem a chamada que a produziu.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositorio.artefatos import gravar_prompt_e_resposta_na_sessao, id_da_explicacao

_INSERIR_EXPLICACAO = text(
    "INSERT INTO explicacoes (id, resultado_id, texto, aderencia_conferida, criado_em)"
    " VALUES (:id, :resultado_id, :texto, :aderencia_conferida, now())"
    " ON CONFLICT DO NOTHING"
)
# A chamada que gerou o texto é a do job, neste nó, cuja resposta é o próprio texto gravado.
_BUSCAR_EXPLICACAO = text(
    "SELECT e.id, e.aderencia_conferida,"
    " (SELECT p.id FROM prompts p JOIN respostas_modelo r ON r.prompt_id = p.id"
    "  WHERE p.job_id = rs.job_id AND p.no = :no AND r.conteudo = e.texto"
    "  ORDER BY p.criado_em, p.id LIMIT 1) AS prompt_id"
    " FROM explicacoes e JOIN resultados_simulacao rs ON rs.id = e.resultado_id"
    " WHERE e.resultado_id = :resultado_id AND rs.job_id = :job_id"
)


@dataclass(frozen=True, slots=True, repr=False)
class ExplicacaoGravada:
    id: UUID
    aderencia_conferida: bool
    #: None quando a chamada que gerou o texto não está mais ligada a ele.
    prompt_id: UUID | None


async def buscar_explicacao(
    sessoes: async_sessionmaker[AsyncSession], *, job_id: UUID, resultado_id: UUID, no: str
) -> ExplicacaoGravada | None:
    """A explicação já gravada para o resultado, com o prompt que a produziu."""
    async with sessoes() as sessao:
        resultado = await sessao.execute(
            _BUSCAR_EXPLICACAO,
            {"resultado_id": resultado_id, "job_id": job_id, "no": no},
        )
        linha = resultado.mappings().one_or_none()
    if linha is None:
        return None
    return ExplicacaoGravada(
        id=UUID(str(linha["id"])),
        aderencia_conferida=bool(linha["aderencia_conferida"]),
        prompt_id=None if linha["prompt_id"] is None else UUID(str(linha["prompt_id"])),
    )


async def gravar_chamada_e_explicacao(
    sessoes: async_sessionmaker[AsyncSession],
    *,
    job_id: UUID,
    resultado_id: UUID,
    no: str,
    prompt: str,
    modelo: dict[str, Any],
    resposta: str,
    consumo_tokens: dict[str, Any] | None,
    conferida: bool | None,
) -> tuple[UUID, UUID | None]:
    """Grava o prompt e a resposta verbatim e, havendo texto, a explicação do resultado.

    `conferida` é None quando a resposta não tem texto a guardar: só a chamada é gravada, para a
    auditoria ver o que o modelo devolveu. Com texto, `aderencia_conferida` diz se todo número
    citado corresponde ao apurado. Returns `(prompt_id, explicacao_id)`.
    """
    async with sessoes() as sessao, sessao.begin():
        prompt_id, _ = await gravar_prompt_e_resposta_na_sessao(
            sessao,
            job_id=job_id,
            no=no,
            prompt=prompt,
            modelo=modelo,
            resposta=resposta,
            consumo_tokens=consumo_tokens,
        )
        if conferida is None:
            return prompt_id, None
        explicacao_id = id_da_explicacao(resultado_id)
        await sessao.execute(
            _INSERIR_EXPLICACAO,
            {
                "id": explicacao_id,
                "resultado_id": resultado_id,
                "texto": resposta,
                "aderencia_conferida": conferida,
            },
        )
    return prompt_id, explicacao_id
