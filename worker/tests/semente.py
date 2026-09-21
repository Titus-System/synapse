"""A cadeia de linhas que um código gerado exige, semeada com o dono do schema.

O worker só tem SELECT em `codigos_gerados` e INSERT em `resultados_simulacao`, e nenhuma
permissão em `jobs`, `regras` ou `prompts`. Quem monta a cadeia de chaves estrangeiras
(usuário → job → regra → prompt → código) e a desfaz é o dono do schema, como o script de seed
de `deploy/scripts/seed.py` faz.
"""

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4


async def semear_codigo(
    conexao: Any,
    *,
    fonte: str,
    competencias: list[str] | None = None,
    orcamento: float = 100000.0,
) -> dict[str, Any]:
    """Cria um job em `simulando` com um código gerado, e devolve os ids da cadeia."""
    competencias = competencias or ["2025-08"]
    usuario_id: UUID = await conexao.fetchval(
        """
        INSERT INTO usuarios (login, senha_hash, nome, papel, criado_em)
        VALUES ($1, 'hash-de-teste', 'Usuário de teste', 'profissional_rh', now())
        RETURNING id
        """,
        f"teste-worker-{uuid4()}@synapse.local",
    )
    job_id: UUID = await conexao.fetchval(
        """
        INSERT INTO jobs (status, usuario_id, competencias, orcamento, criado_em)
        VALUES ('simulando', $1, $2, $3, now())
        RETURNING id
        """,
        usuario_id,
        competencias,
        orcamento,
    )
    nucleo = {"vigencia": {"inicio": competencias[0], "fim": competencias[-1]}}
    regra_id: UUID = await conexao.fetchval(
        """
        INSERT INTO regras (job_id, versao, origem, nucleo, especificacoes, hash, criada_em)
        VALUES ($1, 1, 'confirmacao_usuario', $2::jsonb, $3::jsonb, $4, now())
        RETURNING id
        """,
        job_id,
        json.dumps(nucleo),
        json.dumps([]),
        hashlib.sha256(json.dumps(nucleo).encode("utf-8")).hexdigest(),
    )
    prompt_id: UUID = await conexao.fetchval(
        """
        INSERT INTO prompts (job_id, no, conteudo, modelo, criado_em)
        VALUES ($1, 'geracao_codigo', 'prompt de teste', $2::jsonb, now())
        RETURNING id
        """,
        job_id,
        json.dumps({"provedor": "teste", "modelo": "teste"}),
    )
    codigo_gerado_id: UUID = await conexao.fetchval(
        """
        INSERT INTO codigos_gerados (job_id, regra_id, linguagem, fonte, prompt_id, criado_em)
        VALUES ($1, $2, 'python', $3, $4, now())
        RETURNING id
        """,
        job_id,
        regra_id,
        fonte,
        prompt_id,
    )
    return {
        "id": codigo_gerado_id,
        "job_id": job_id,
        "linguagem": "python",
        "fonte": fonte,
        "usuario_id": usuario_id,
        "regra_id": regra_id,
        "prompt_id": prompt_id,
    }


async def apagar_semente(conexao: Any, semente: dict[str, Any]) -> None:
    """Desfaz a cadeia. Os resultados primeiro: o worker não os apaga (só tem INSERT), e a linha
    aponta o código e o job por chave estrangeira."""
    # Por job e por código: uma linha gravada por engano para outro job ainda aponta este código.
    await conexao.execute(
        "DELETE FROM resultados_simulacao WHERE job_id = $1 OR codigo_gerado_id = $2",
        semente["job_id"],
        semente["id"],
    )
    await conexao.execute("DELETE FROM codigos_gerados WHERE id = $1", semente["id"])
    await conexao.execute("DELETE FROM prompts WHERE id = $1", semente["prompt_id"])
    await conexao.execute("DELETE FROM regras WHERE id = $1", semente["regra_id"])
    await conexao.execute("DELETE FROM jobs WHERE id = $1", semente["job_id"])
    await conexao.execute("DELETE FROM usuarios WHERE id = $1", semente["usuario_id"])
