from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.engine import get_sessionmaker
from app.repositorio.codigos_gerados import CodigoNaoEncontradoError, buscar_codigo

pytestmark = pytest.mark.postgres


async def test_busca_codigo_existente_pela_referencia(
    codigo_gerado_seed: dict[str, object],
) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as sessao:
        codigo = await buscar_codigo(sessao, codigo_gerado_seed["id"])

    assert codigo.id == codigo_gerado_seed["id"]
    assert codigo.job_id == codigo_gerado_seed["job_id"]
    assert codigo.linguagem == codigo_gerado_seed["linguagem"]
    assert codigo.fonte == codigo_gerado_seed["fonte"]


async def test_referencia_inexistente_levanta_erro_especifico() -> None:
    codigo_gerado_id = uuid4()
    sessionmaker = get_sessionmaker()

    with pytest.raises(CodigoNaoEncontradoError) as excinfo:
        async with sessionmaker() as sessao:
            await buscar_codigo(sessao, codigo_gerado_id)

    assert excinfo.value.codigo_gerado_id == codigo_gerado_id


async def test_worker_nao_pode_alterar_codigos_gerados(
    codigo_gerado_seed: dict[str, object],
) -> None:
    sessionmaker = get_sessionmaker()

    with pytest.raises(DBAPIError, match="permission denied"):
        async with sessionmaker() as sessao:
            await sessao.execute(
                text("UPDATE codigos_gerados SET linguagem = 'outra' WHERE id = :id"),
                {"id": codigo_gerado_seed["id"]},
            )
