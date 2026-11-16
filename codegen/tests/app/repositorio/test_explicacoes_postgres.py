"""As consultas da explicação do resultado no Postgres real, com as migrations da api."""

import os
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import simplejson
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositorio.artefatos import id_da_explicacao
from app.repositorio.explicacoes import buscar_explicacao, gravar_chamada_e_explicacao
from app.repositorio.resultados import (
    ResultadoDesconhecidoError,
    buscar_decomposicao,
    buscar_totais_apurados,
)
from tests.app.repositorio.test_tentativas_postgres import Historico, banco

__all__ = ["banco"]

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="Requer Docker; habilitar com RUN_POSTGRES_INTEGRATION=1",
    ),
]

Banco = tuple[async_sessionmaker[AsyncSession], Historico]
TOTAIS = {
    "baseline": Decimal("480312.10"),
    "simulado": Decimal("492100"),
    "diferenca_abs": Decimal("11787.90"),
    "diferenca_pct": Decimal("0.0245"),
}
DECOMPOSICAO = {
    "elemento": {"nucleo.percentual": Decimal("11787.90")},
    "loja": {"13": Decimal("11787.90")},
    "marca": {"10": Decimal("11787.90")},
    "cargo": {"100": Decimal("11787.90")},
    "competencia": {"2025-11": Decimal("11787.90")},
    "matricula": {"MATRIC-422": Decimal("141300")},
    "loja_absoluto": {"13": Decimal("492100")},
}
NO = "explicacao"


async def _resultado(
    historico: Historico, *, totais: Any = TOTAIS, decomposicao: Any = None
) -> tuple[UUID, UUID]:
    job = await historico.job()
    regra = await historico.versao(job, 1, "extracao", "0.025")
    resultado = await historico.resultado(job, regra, "492100")
    await historico._dono.execute(
        "UPDATE resultados_simulacao SET totais = $2::jsonb, decomposicao = $3::jsonb"
        " WHERE id = $1",
        resultado,
        None if totais is None else simplejson.dumps(totais, use_decimal=True),
        None if decomposicao is None else simplejson.dumps(decomposicao, use_decimal=True),
    )
    return job, resultado


async def test_os_totais_apurados_voltam_com_o_valor_exato_gravado(banco: Banco) -> None:
    sessoes, historico = banco
    job, resultado = await _resultado(historico)

    totais = await buscar_totais_apurados(sessoes, job, resultado)

    assert totais == TOTAIS
    assert str(totais["baseline"]) == "480312.10"


async def test_o_resultado_sem_orcamento_ainda_tem_totais_a_narrar(banco: Banco) -> None:
    sessoes, historico = banco
    job, resultado = await _resultado(historico)

    totais = await buscar_totais_apurados(sessoes, job, resultado)

    assert "orcamento" not in totais
    assert totais["simulado"] == Decimal("492100")


async def test_a_decomposicao_sai_do_banco_sem_a_quebra_por_matricula(banco: Banco) -> None:
    sessoes, historico = banco
    job, resultado = await _resultado(historico, decomposicao=DECOMPOSICAO)

    decomposicao = await buscar_decomposicao(sessoes, job, resultado)

    assert "matricula" not in decomposicao
    assert decomposicao["loja"] == {"13": Decimal("11787.90")}
    assert decomposicao["loja_absoluto"] == {"13": Decimal("492100")}
    assert "MATRIC-422" not in simplejson.dumps(decomposicao, use_decimal=True)


async def test_resultado_de_outro_job_ou_sem_decomposicao_e_desconhecido(banco: Banco) -> None:
    sessoes, historico = banco
    job, resultado = await _resultado(historico)

    with pytest.raises(ResultadoDesconhecidoError):
        await buscar_totais_apurados(sessoes, uuid4(), resultado)
    with pytest.raises(ResultadoDesconhecidoError):
        await buscar_decomposicao(sessoes, job, resultado)


async def test_grava_a_chamada_e_a_explicacao_juntas_e_a_reexecucao_nao_duplica(
    banco: Banco,
) -> None:
    sessoes, historico = banco
    job, resultado = await _resultado(historico, decomposicao=DECOMPOSICAO)
    argumentos: dict[str, Any] = {
        "job_id": job,
        "resultado_id": resultado,
        "no": NO,
        "prompt": "prompt da explicação",
        "modelo": {"provedor": "google"},
        "resposta": "A narrativa.",
        "consumo_tokens": {"tokens_in": 10, "tokens_out": 5},
        "conferida": True,
    }
    assert await buscar_explicacao(sessoes, job_id=job, resultado_id=resultado, no=NO) is None

    prompt_id, explicacao_id = await gravar_chamada_e_explicacao(sessoes, **argumentos)
    repetida = await gravar_chamada_e_explicacao(sessoes, **argumentos)

    assert explicacao_id == id_da_explicacao(resultado)
    assert repetida == (prompt_id, explicacao_id)
    gravada = await buscar_explicacao(sessoes, job_id=job, resultado_id=resultado, no=NO)
    assert gravada is not None
    assert (gravada.id, gravada.aderencia_conferida, gravada.prompt_id) == (
        explicacao_id,
        True,
        prompt_id,
    )
    dono = historico._dono
    assert (
        await dono.fetchval("SELECT count(*) FROM explicacoes WHERE resultado_id = $1", resultado)
        == 1
    )
    assert (
        await dono.fetchval("SELECT texto FROM explicacoes WHERE id = $1", explicacao_id)
        == "A narrativa."
    )
    assert (
        await dono.fetchval("SELECT conteudo FROM respostas_modelo WHERE prompt_id = $1", prompt_id)
        == "A narrativa."
    )


async def test_a_narrativa_reprovada_fica_gravada_com_aderencia_falsa(banco: Banco) -> None:
    sessoes, historico = banco
    job, resultado = await _resultado(historico, decomposicao=DECOMPOSICAO)

    await gravar_chamada_e_explicacao(
        sessoes,
        job_id=job,
        resultado_id=resultado,
        no=NO,
        prompt="p",
        modelo={},
        resposta="A loja respondeu por 61,4%.",
        consumo_tokens=None,
        conferida=False,
    )

    gravada = await buscar_explicacao(sessoes, job_id=job, resultado_id=resultado, no=NO)
    assert gravada is not None
    assert gravada.aderencia_conferida is False


async def test_sem_texto_so_a_chamada_e_gravada(banco: Banco) -> None:
    sessoes, historico = banco
    job, resultado = await _resultado(historico, decomposicao=DECOMPOSICAO)

    prompt_id, explicacao_id = await gravar_chamada_e_explicacao(
        sessoes,
        job_id=job,
        resultado_id=resultado,
        no=NO,
        prompt="p",
        modelo={},
        resposta="",
        consumo_tokens=None,
        conferida=None,
    )

    assert explicacao_id is None
    assert await buscar_explicacao(sessoes, job_id=job, resultado_id=resultado, no=NO) is None
    dono = historico._dono
    assert (
        await dono.fetchval("SELECT count(*) FROM respostas_modelo WHERE prompt_id = $1", prompt_id)
        == 1
    )


async def test_a_explicacao_de_outro_job_nao_e_devolvida(banco: Banco) -> None:
    sessoes, historico = banco
    job, resultado = await _resultado(historico, decomposicao=DECOMPOSICAO)
    await gravar_chamada_e_explicacao(
        sessoes,
        job_id=job,
        resultado_id=resultado,
        no=NO,
        prompt="p",
        modelo={},
        resposta="Texto.",
        consumo_tokens=None,
        conferida=True,
    )

    assert await buscar_explicacao(sessoes, job_id=uuid4(), resultado_id=resultado, no=NO) is None
