"""Falhas do provedor não podem mascarar regressões de um teste com modelo real."""

from unittest.mock import AsyncMock

import pytest
from google.genai.errors import ServerError

from tests.app.apoio_provedor_real import executar_com_retentativa_503


def _servidor(codigo: int) -> ServerError:
    return ServerError(codigo, {"error": {"status": "UNAVAILABLE"}})


async def test_503_transitorio_faz_uma_nova_tentativa(monkeypatch: pytest.MonkeyPatch) -> None:
    espera = AsyncMock()
    monkeypatch.setattr("tests.app.apoio_provedor_real.asyncio.sleep", espera)
    chamada = AsyncMock(side_effect=[_servidor(503), "resultado válido"])

    resultado = await executar_com_retentativa_503(chamada)

    assert resultado == "resultado válido"
    assert chamada.await_count == 2
    espera.assert_awaited_once_with(2)


async def test_503_persistente_registra_caso_nao_verificado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tests.app.apoio_provedor_real.asyncio.sleep", AsyncMock())
    chamada = AsyncMock(side_effect=[_servidor(503), _servidor(503)])

    with pytest.raises(pytest.skip.Exception, match="HTTP 503 após duas tentativas"):
        await executar_com_retentativa_503(chamada)

    assert chamada.await_count == 2


async def test_503_encapsulado_pelo_sdk_tambem_faz_retentativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tests.app.apoio_provedor_real.asyncio.sleep", AsyncMock())
    erro = RuntimeError("erro encapsulado")
    erro.__cause__ = _servidor(503)
    chamada = AsyncMock(side_effect=[erro, "resultado válido"])

    assert await executar_com_retentativa_503(chamada) == "resultado válido"
    assert chamada.await_count == 2


@pytest.mark.parametrize("erro", [_servidor(500), ValueError("503 no conteúdo")])
async def test_outros_erros_continuam_falhando(erro: Exception) -> None:
    chamada = AsyncMock(side_effect=erro)

    with pytest.raises(type(erro)):
        await executar_com_retentativa_503(chamada)

    chamada.assert_awaited_once_with()
