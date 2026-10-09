import asyncio
import os
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
import simplejson

from app.repositorio.extracoes import PersistenciaExtracaoError, buscar_extracao, gravar_extracao
from tests.app.extracao.test_motor import ELEMENTO, PARAMETROS_BRUTOS, extrair, modelo_falso

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="Requer Docker; habilitar com RUN_POSTGRES_INTEGRATION=1",
    ),
]


async def resultado() -> Any:
    return await extrair(
        modelo_falso(
            {
                "nucleo": {"loja": ["0013"], "percentual": Decimal("2.1234567890123456789")},
                "elementos": [ELEMENTO],
                "parametros": PARAMETROS_BRUTOS,
            }
        )
    )


async def contagens(dono: Any, job: Any) -> list[int]:
    return [
        await dono.fetchval(f"SELECT count(*) FROM {tabela} WHERE job_id=$1", job)
        for tabela in ("prompts", "respostas_modelo", "extracoes_regras")
    ]


async def test_grava_e_recupera_os_tres_artefatos_com_referencias(banco_extracao: Any) -> None:
    sessoes, dono, job, submissao = banco_extracao
    extraido = await resultado()

    salvo = await gravar_extracao(sessoes, job_id=job, submissao_id=submissao, resultado=extraido)
    lido = await buscar_extracao(sessoes, job_id=job, submissao_id=submissao)

    assert lido == salvo
    assert salvo.representacao.para_contrato() == extraido.representacao.para_contrato()
    assert salvo.rebaixamentos == extraido.rebaixamentos
    assert (
        salvo.parametros
        == extraido.parametros
        == {
            "orcamento": Decimal("500000"),
            "meta_venda": Decimal("12000000"),
            "competencias": ["2025-09", "2025-10", "2025-11"],
        }
    )
    assert await contagens(dono, job) == [1, 1, 1]
    assert (
        await dono.fetchval("SELECT conteudo FROM prompts WHERE id=$1", salvo.prompt_id)
        == extraido.chamada.prompt
    )
    assert (
        await dono.fetchval("SELECT conteudo FROM respostas_modelo WHERE id=$1", salvo.resposta_id)
        == extraido.chamada.resposta
    )
    parametros_no_banco = await dono.fetchval(
        "SELECT parametros::text FROM extracoes_regras WHERE id=$1", salvo.id
    )
    assert simplejson.loads(parametros_no_banco, use_decimal=True) == salvo.parametros


async def test_reentrega_retorna_artefato_original_mesmo_com_outra_resposta(
    banco_extracao: Any,
) -> None:
    sessoes, dono, job, submissao = banco_extracao
    original = await resultado()
    salvo = await gravar_extracao(sessoes, job_id=job, submissao_id=submissao, resultado=original)
    diferente = await extrair(
        modelo_falso({"nucleo": {"percentual": 2}, "elementos": [], "parametros": {}})
    )

    repetido = await gravar_extracao(
        sessoes, job_id=job, submissao_id=submissao, resultado=diferente
    )

    assert repetido == salvo
    assert await contagens(dono, job) == [1, 1, 1]


async def test_concorrencia_reverte_artefatos_da_transacao_perdedora(banco_extracao: Any) -> None:
    sessoes, dono, job, submissao = banco_extracao
    resultados = [
        await extrair(
            modelo_falso({"nucleo": {"percentual": i}, "elementos": [], "parametros": {}})
        )
        for i in range(8)
    ]

    salvos = await asyncio.gather(
        *[
            gravar_extracao(sessoes, job_id=job, submissao_id=submissao, resultado=r)
            for r in resultados
        ]
    )

    assert all(salvo == salvos[0] for salvo in salvos)
    assert await contagens(dono, job) == [1, 1, 1]
    resposta = await dono.fetchval(
        "SELECT conteudo FROM respostas_modelo WHERE id=$1", salvos[0].resposta_id
    )
    assert (
        simplejson.loads(resposta, use_decimal=True)["nucleo"]
        == salvos[0].representacao.para_contrato()["nucleo"]
    )


async def test_falha_no_ultimo_insert_reverte_prompt_e_resposta_sem_expor_dados(
    banco_extracao: Any,
) -> None:
    sessoes, dono, job, submissao = banco_extracao
    extraido = await resultado()
    await dono.execute("""
        CREATE FUNCTION recusar_extracao_teste() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'conteudo-sigiloso-teste'; END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER recusar_extracao BEFORE INSERT ON extracoes_regras
        FOR EACH ROW EXECUTE FUNCTION recusar_extracao_teste();
    """)
    try:
        with pytest.raises(PersistenciaExtracaoError) as erro:
            await gravar_extracao(sessoes, job_id=job, submissao_id=submissao, resultado=extraido)
        assert erro.value.__context__ is None
        assert "conteudo-sigiloso-teste" not in str(erro.value)
        assert await contagens(dono, job) == [0, 0, 0]
    finally:
        await dono.execute(
            "DROP TRIGGER recusar_extracao ON extracoes_regras; "
            "DROP FUNCTION recusar_extracao_teste()"
        )


async def test_consulta_ausente_nao_cria_artefatos(banco_extracao: Any) -> None:
    sessoes, dono, job, submissao = banco_extracao

    assert await buscar_extracao(sessoes, job_id=job, submissao_id=submissao) is None
    assert await contagens(dono, job) == [0, 0, 0]


async def test_diagnostico_invalido_nao_e_persistido(banco_extracao: Any) -> None:
    sessoes, dono, job, submissao = banco_extracao
    extraido = await resultado()
    extraido = replace(extraido, rebaixamentos=[replace(extraido.rebaixamentos[0], ref="elem.999")])

    with pytest.raises(ValueError):
        await gravar_extracao(sessoes, job_id=job, submissao_id=submissao, resultado=extraido)

    assert await contagens(dono, job) == [0, 0, 0]
