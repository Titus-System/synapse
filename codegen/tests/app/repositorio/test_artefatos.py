from uuid import uuid4

import pytest
import simplejson

from app.repositorio.artefatos import gravar_codigo, gravar_prompt_e_resposta
from tests.app.banco_falso import BancoFalso

JOB_ID = uuid4()
REGRA_ID = uuid4()
MODELO = {"provedor": "google", "modelo": "m", "versao": "stable"}


async def _gravar(banco: BancoFalso, resposta: str = "resposta") -> tuple[object, object]:
    return await gravar_prompt_e_resposta(
        banco,  # type: ignore[arg-type]
        job_id=JOB_ID,
        no="geracao_codigo",
        prompt="prompt",
        modelo=MODELO,
        resposta=resposta,
        consumo_tokens={"tokens_in": 1, "tokens_out": 2},
    )


async def test_grava_prompt_e_resposta_com_referencia_cruzada() -> None:
    banco = BancoFalso()

    prompt_id, resposta_id = await _gravar(banco)

    [prompt] = banco.tabela("prompts")
    [resposta] = banco.tabela("respostas_modelo")
    assert prompt["id"] == prompt_id
    assert prompt["job_id"] == JOB_ID
    assert prompt["no"] == "geracao_codigo"
    assert prompt["conteudo"] == "prompt"
    assert simplejson.loads(prompt["modelo"]) == MODELO
    assert resposta["id"] == resposta_id
    assert resposta["prompt_id"] == prompt_id
    assert resposta["conteudo"] == "resposta"
    assert simplejson.loads(resposta["consumo_tokens"]) == {"tokens_in": 1, "tokens_out": 2}


async def test_grava_consumo_nulo_quando_o_provedor_nao_informa() -> None:
    banco = BancoFalso()

    await gravar_prompt_e_resposta(
        banco,  # type: ignore[arg-type]
        job_id=JOB_ID,
        no="geracao_codigo",
        prompt="prompt",
        modelo=MODELO,
        resposta="resposta",
        consumo_tokens=None,
    )

    assert banco.tabela("respostas_modelo")[0]["consumo_tokens"] is None


async def test_regravar_os_mesmos_insumos_nao_cria_outra_linha() -> None:
    banco = BancoFalso()

    primeira = await _gravar(banco)
    segunda = await _gravar(banco)

    assert primeira == segunda
    assert len(banco.tabela("prompts")) == 1
    assert len(banco.tabela("respostas_modelo")) == 1


async def test_outra_resposta_ao_mesmo_prompt_e_outra_chamada() -> None:
    banco = BancoFalso()

    primeira = await _gravar(banco, resposta="uma")
    segunda = await _gravar(banco, resposta="outra")

    assert primeira[0] != segunda[0]
    assert len(banco.tabela("prompts")) == 2


async def test_falha_na_resposta_nao_deixa_o_prompt_gravado() -> None:
    banco = BancoFalso(falhar_em=("respostas_modelo",))

    with pytest.raises(RuntimeError):
        await _gravar(banco)

    assert banco.tabela("prompts") == []


async def test_grava_codigo_com_as_referencias_e_de_forma_idempotente() -> None:
    banco = BancoFalso()
    prompt_id = uuid4()

    primeiro = await gravar_codigo(
        banco,  # type: ignore[arg-type]
        job_id=JOB_ID,
        regra_id=REGRA_ID,
        prompt_id=prompt_id,
        fonte="def f(): ...",
    )
    segundo = await gravar_codigo(
        banco,  # type: ignore[arg-type]
        job_id=JOB_ID,
        regra_id=REGRA_ID,
        prompt_id=prompt_id,
        fonte="def f(): ...",
    )

    assert primeiro == segundo
    [codigo] = banco.tabela("codigos_gerados")
    assert codigo == {
        "id": primeiro,
        "job_id": JOB_ID,
        "regra_id": REGRA_ID,
        "linguagem": "python",
        "fonte": "def f(): ...",
        "prompt_id": prompt_id,
    }


async def test_todo_insert_ignora_conflito_e_nunca_atualiza() -> None:
    """The codegen user only has INSERT on these tables: an UPDATE would fail in production."""
    banco = BancoFalso()

    await _gravar(banco)
    await gravar_codigo(
        banco,  # type: ignore[arg-type]
        job_id=JOB_ID,
        regra_id=REGRA_ID,
        prompt_id=uuid4(),
        fonte="x",
    )

    assert len(banco.sql_executado) == 3
    assert all(sql.endswith("ON CONFLICT DO NOTHING") for sql in banco.sql_executado)
    assert not any("UPDATE" in sql for sql in banco.sql_executado)
