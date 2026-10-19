"""Retentativa limitada de testes com LLM real quando o provedor responde HTTP 503."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from google.genai.errors import ServerError


def _erro_503(erro: BaseException) -> bool:
    visitados: set[int] = set()
    atual: BaseException | None = erro
    while atual is not None and id(atual) not in visitados:
        visitados.add(id(atual))
        if isinstance(atual, ServerError) and atual.code == 503:
            return True
        atual = atual.__cause__ or atual.__context__
    return False


async def executar_com_retentativa_503[T](chamada: Callable[[], Awaitable[T]]) -> T:
    """Não confunde indisponibilidade persistente do Gemini com falha de extração.

    O SDK já tenta novamente internamente; há no máximo uma chamada extra aqui.
    Apenas 503 persistente é ignorado, com motivo explícito no relatório do pytest.
    """
    try:
        return await chamada()
    except Exception as erro:
        if not _erro_503(erro):
            raise

    await asyncio.sleep(2)
    try:
        return await chamada()
    except Exception as erro:
        if _erro_503(erro):
            pytest.skip("provedor indisponível (HTTP 503 após duas tentativas)")
        raise
