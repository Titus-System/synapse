"""Escrita e consulta de `resultados_simulacao` com o usuário real do worker (T-067).

O worker tem `SELECT` e `INSERT` nesta tabela e nenhuma permissão em outra: uma linha gravada não
se altera nem se apaga. Os testes de permissão rodam contra o Postgres do compose, onde as
migrations da api concederam (ou não) cada privilégio.
"""

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.engine import get_sessionmaker
from app.repositorio.resultados import buscar_resultado, gravar_resultado

pytestmark = pytest.mark.postgres

TOTAIS = {
    "baseline": 480312.0,
    "simulado": 492100.0,
    "diferenca_abs": 11788.0,
    "diferenca_pct": 0.0245,
    "orcamento": 485000.0,
}
ASSERCOES = [{"nome": "sem_comissao_negativa", "resultado": "ok", "detalhe": None}]
DECOMPOSICAO = {
    "elemento": {"nucleo.percentual": 8200.0},
    "loja": {"13": 7100.0},
    "marca": {"10": 11788.0},
    "cargo": {"100": 9200.0},
    "competencia": {"2025-08": 0.0, "2025-11": 11788.0},
}


async def gravar(seed: dict[str, object], **mudancas: Any) -> UUID:
    campos: dict[str, Any] = {
        "job_id": seed["job_id"],
        "codigo_gerado_id": seed["id"],
        "status": "sucesso",
        "veredito": "inviavel",
        "totais": TOTAIS,
        "assercoes": ASSERCOES,
        "decomposicao": DECOMPOSICAO,
    }
    async with get_sessionmaker()() as sessao, sessao.begin():
        gravado = await gravar_resultado(sessao, **(campos | mudancas))
    return gravado.id


async def ler_como_dono(conexao_dono: Any, resultado_id: UUID) -> Any:
    return await conexao_dono.fetchrow(
        "SELECT * FROM resultados_simulacao WHERE id = $1", resultado_id
    )


# ---- gravar ----


async def test_grava_a_linha_com_todas_as_colunas(
    codigo_gerado_seed: dict[str, object], conexao_dono: Any
) -> None:
    resultado_id = await gravar(codigo_gerado_seed)

    linha = await ler_como_dono(conexao_dono, resultado_id)

    assert linha["job_id"] == codigo_gerado_seed["job_id"]
    assert linha["codigo_gerado_id"] == codigo_gerado_seed["id"]
    assert (linha["status"], linha["veredito"]) == ("sucesso", "inviavel")
    assert json.loads(linha["totais"]) == TOTAIS
    assert json.loads(linha["assercoes"]) == ASSERCOES
    assert json.loads(linha["decomposicao"]) == DECOMPOSICAO
    assert linha["criado_em"] is not None


async def test_o_id_devolvido_e_o_da_linha_gravada(
    codigo_gerado_seed: dict[str, object], conexao_dono: Any
) -> None:
    resultado_id = await gravar(codigo_gerado_seed)

    assert await ler_como_dono(conexao_dono, resultado_id) is not None


async def test_o_que_nao_e_sucesso_grava_nulos_e_assercoes_vazias(
    codigo_gerado_seed: dict[str, object], conexao_dono: Any
) -> None:
    resultado_id = await gravar(
        codigo_gerado_seed,
        status="erro_infra",
        veredito=None,
        totais=None,
        assercoes=[],
        decomposicao=None,
    )

    linha = await ler_como_dono(conexao_dono, resultado_id)

    assert linha["status"] == "erro_infra"
    assert (linha["veredito"], linha["totais"], linha["decomposicao"]) == (None, None, None)
    assert json.loads(linha["assercoes"]) == []


async def test_a_linha_nao_existe_para_outros_ate_a_transacao_confirmar(
    codigo_gerado_seed: dict[str, object], conexao_dono: Any
) -> None:
    """É a garantia de "gravar antes de publicar": só o que confirmou pode ser referenciado."""
    async with get_sessionmaker()() as sessao:
        sessao_tx = await sessao.begin()
        gravado = await gravar_resultado(
            sessao,
            job_id=codigo_gerado_seed["job_id"],  # type: ignore[arg-type]
            codigo_gerado_id=codigo_gerado_seed["id"],  # type: ignore[arg-type]
            status="sucesso",
            veredito="viavel",
            totais=TOTAIS,
            assercoes=ASSERCOES,
            decomposicao=DECOMPOSICAO,
        )
        assert await ler_como_dono(conexao_dono, gravado.id) is None
        await sessao_tx.rollback()

    assert await ler_como_dono(conexao_dono, gravado.id) is None


async def test_job_inexistente_viola_a_chave_estrangeira(
    codigo_gerado_seed: dict[str, object],
) -> None:
    with pytest.raises(IntegrityError, match="fk_resultados_simulacao_job_id"):
        await gravar(codigo_gerado_seed, job_id=uuid4())


async def test_codigo_inexistente_viola_a_chave_estrangeira(
    codigo_gerado_seed: dict[str, object],
) -> None:
    with pytest.raises(IntegrityError, match="fk_resultados_simulacao_codigo_gerado_id"):
        await gravar(codigo_gerado_seed, codigo_gerado_id=uuid4())


async def test_agregado_nao_finito_nao_chega_ao_banco(
    codigo_gerado_seed: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="Out of range"):
        await gravar(codigo_gerado_seed, totais={**TOTAIS, "simulado": float("nan")})


# ---- consultar ----


async def test_busca_a_linha_gravada_para_o_par_job_e_codigo(
    codigo_gerado_seed: dict[str, object],
) -> None:
    resultado_id = await gravar(codigo_gerado_seed)

    async with get_sessionmaker()() as sessao:
        achado = await buscar_resultado(
            sessao,
            codigo_gerado_seed["job_id"],  # type: ignore[arg-type]
            codigo_gerado_seed["id"],  # type: ignore[arg-type]
        )

    assert achado is not None
    assert (achado.id, achado.status, achado.veredito) == (resultado_id, "sucesso", "inviavel")
    assert achado.totais == TOTAIS


async def test_sem_linha_a_busca_devolve_nada(codigo_gerado_seed: dict[str, object]) -> None:
    async with get_sessionmaker()() as sessao:
        assert (
            await buscar_resultado(
                sessao,
                codigo_gerado_seed["job_id"],  # type: ignore[arg-type]
                codigo_gerado_seed["id"],  # type: ignore[arg-type]
            )
            is None
        )


async def test_a_busca_ignora_erro_infra(codigo_gerado_seed: dict[str, object]) -> None:
    """Um comando reenviado da DLQ tem de executar de novo, e não republicar o erro que o
    mandou para lá."""
    await gravar(
        codigo_gerado_seed,
        status="erro_infra",
        veredito=None,
        totais=None,
        assercoes=[],
        decomposicao=None,
    )

    async with get_sessionmaker()() as sessao:
        achado = await buscar_resultado(
            sessao,
            codigo_gerado_seed["job_id"],  # type: ignore[arg-type]
            codigo_gerado_seed["id"],  # type: ignore[arg-type]
        )

    assert achado is None


async def test_a_busca_devolve_a_linha_mais_antiga_quando_ha_mais_de_uma(
    codigo_gerado_seed: dict[str, object],
) -> None:
    primeira = await gravar(codigo_gerado_seed)
    await gravar(codigo_gerado_seed, veredito="viavel")

    async with get_sessionmaker()() as sessao:
        achado = await buscar_resultado(
            sessao,
            codigo_gerado_seed["job_id"],  # type: ignore[arg-type]
            codigo_gerado_seed["id"],  # type: ignore[arg-type]
        )

    assert achado is not None and achado.id == primeira


# ---- permissões: o worker só insere ----


@pytest.mark.parametrize(
    "instrucao",
    [
        "UPDATE resultados_simulacao SET status = 'sucesso' WHERE id = :id",
        "DELETE FROM resultados_simulacao WHERE id = :id",
    ],
    ids=["update", "delete"],
)
async def test_worker_nao_altera_nem_apaga_resultado(
    codigo_gerado_seed: dict[str, object], instrucao: str
) -> None:
    resultado_id = await gravar(codigo_gerado_seed)

    with pytest.raises(DBAPIError, match="permission denied"):
        async with get_sessionmaker()() as sessao, sessao.begin():
            await sessao.execute(text(instrucao), {"id": resultado_id})


async def test_a_linha_continua_intacta_depois_da_tentativa_de_alterar(
    codigo_gerado_seed: dict[str, object], conexao_dono: Any
) -> None:
    resultado_id = await gravar(codigo_gerado_seed)
    with pytest.raises(DBAPIError):
        async with get_sessionmaker()() as sessao, sessao.begin():
            await sessao.execute(
                text("UPDATE resultados_simulacao SET veredito = 'viavel' WHERE id = :id"),
                {"id": resultado_id},
            )

    assert (await ler_como_dono(conexao_dono, resultado_id))["veredito"] == "inviavel"


@pytest.mark.parametrize(
    "tabela", ["jobs", "codigos_gerados", "simulacoes", "explicacoes", "outbox_events"]
)
async def test_worker_nao_escreve_em_nenhuma_outra_tabela(tabela: str) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with get_sessionmaker()() as sessao, sessao.begin():
            await sessao.execute(text(f"INSERT INTO {tabela} DEFAULT VALUES"))
