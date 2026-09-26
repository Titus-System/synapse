"""In-memory stand-in for the `sessoes` sessionmaker, for code that only inserts artifacts.

Inserts are kept per transaction and applied on commit, so a failure inside `sessao.begin()`
leaves nothing behind. A row whose id already exists is skipped, as the real inserts'
`ON CONFLICT DO NOTHING` does.
"""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

_TABELA = re.compile(r"INSERT INTO (\w+)")


class SessaoFalsa:
    def __init__(self, banco: "BancoFalso") -> None:
        self._banco = banco
        self._pendentes: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        sql = str(statement)
        self._banco.sql_executado.append(sql)
        tabela = _TABELA.search(sql)
        assert tabela is not None, "BancoFalso only supports INSERT statements"
        if tabela.group(1) in self._banco.falhar_em:
            raise RuntimeError("simulated database failure")
        self._pendentes.append((tabela.group(1), dict(params)))

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield
        for tabela, linha in self._pendentes:
            self._banco.linhas.setdefault(tabela, {}).setdefault(linha["id"], linha)
        self._pendentes.clear()


class BancoFalso:
    def __init__(self, *, falhar_em: tuple[str, ...] = ()) -> None:
        self.linhas: dict[str, dict[Any, dict[str, Any]]] = {}
        self.sql_executado: list[str] = []
        self.falhar_em = falhar_em

    def tabela(self, nome: str) -> list[dict[str, Any]]:
        return list(self.linhas.get(nome, {}).values())

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SessaoFalsa]:
        yield SessaoFalsa(self)
