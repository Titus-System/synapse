from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from tests.app.banco_falso import BancoFalso, SessaoFalsa


class ResultadoFalso:
    def __init__(self, linha: dict[str, Any] | None) -> None:
        self.linha = linha

    def mappings(self) -> "ResultadoFalso":
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self.linha

    def scalar_one_or_none(self) -> Any:
        return None if self.linha is None else self.linha["id"]


class SessaoExtracaoFalsa(SessaoFalsa):
    def __init__(self, banco: "BancoExtracaoFalso") -> None:
        super().__init__(banco)
        self.banco = banco

    async def execute(self, statement: Any, params: dict[str, Any]) -> Any:
        sql = str(statement)
        if sql.startswith("SELECT transcricao"):
            self.banco.sql_executado.append(sql)
            texto = self.banco.transcricoes.get(params["submissao_id"])
            return ResultadoFalso(None if texto is None else {"transcricao": texto})
        if sql.startswith("SELECT e.id"):
            self.banco.sql_executado.append(sql)
            for extracao in self.banco.tabela("extracoes_regras"):
                if all(extracao[chave] == params[chave] for chave in ("job_id", "submissao_id")):
                    resposta = next(
                        r
                        for r in self.banco.tabela("respostas_modelo")
                        if r["id"] == extracao["resposta_id"]
                    )
                    return ResultadoFalso({**extracao, "prompt_id": resposta["prompt_id"]})
            return ResultadoFalso(None)
        await super().execute(statement, params)
        return ResultadoFalso({"id": params["id"]})


class BancoExtracaoFalso(BancoFalso):
    def __init__(self) -> None:
        super().__init__()
        self.transcricoes: dict[UUID, str | None] = {}

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SessaoExtracaoFalsa]:
        yield SessaoExtracaoFalsa(self)
