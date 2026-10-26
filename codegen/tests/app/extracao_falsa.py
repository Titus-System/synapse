from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import simplejson

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


class ResultadoHistoricoFalso:
    def __init__(self, linhas: list[dict[str, Any]]) -> None:
        self.linhas = linhas

    def mappings(self) -> "ResultadoHistoricoFalso":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.linhas


class SessaoExtracaoFalsa(SessaoFalsa):
    def __init__(self, banco: "BancoExtracaoFalso") -> None:
        super().__init__(banco)
        self.banco = banco

    async def execute(self, statement: Any, params: dict[str, Any]) -> Any:
        sql = str(statement)
        if sql.startswith("WITH RECURSIVE cadeia"):
            self.banco.sql_executado.append(sql)
            anteriores = self.banco.rodadas_correcao
            atuais = [
                r
                for r in anteriores
                if str(r["job_id"]) == params["job_id"]
                and str(r["submissao_correcao_id"]) == params["submissao_id"]
            ]
            if not atuais:
                return ResultadoHistoricoFalso([])
            atual = atuais[0]
            linhas: list[dict[str, Any]] = []
            for _ in range(params["limite"]):
                anterior = next(
                    (
                        r
                        for r in anteriores
                        if r["id"] == atual["rodada_anterior_id"]
                        and str(r["job_id"]) == params["job_id"]
                    ),
                    None,
                )
                if anterior is None:
                    break
                linhas.append(
                    {
                        "conflitos": simplejson.dumps(anterior["conflitos"]),
                        "texto": self.banco.transcricoes.get(anterior["submissao_correcao_id"]),
                    }
                )
                atual = anterior
            return ResultadoHistoricoFalso(list(reversed(linhas)))
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
        if sql.startswith("SELECT p.id AS prompt_id"):
            self.banco.sql_executado.append(sql)
            # Só as respostas gravadas depois da submissão, como `r.criado_em >= s.criado_em`.
            desde = self.banco.respostas_antes_da_submissao.get(params["submissao_id"], 0)
            respostas = self.banco.tabela("respostas_modelo")[desde:]
            for prompt in self.banco.tabela("prompts"):
                chave = (prompt["job_id"], prompt["no"], prompt["conteudo"])
                resposta = next((r for r in respostas if r["prompt_id"] == prompt["id"]), None)
                if resposta is not None and chave == (
                    params["job_id"],
                    params["no"],
                    params["prompt"],
                ):
                    return ResultadoFalso(
                        {
                            "prompt_id": prompt["id"],
                            "resposta_id": resposta["id"],
                            "conteudo": resposta["conteudo"],
                        }
                    )
            return ResultadoFalso(None)
        await super().execute(statement, params)
        return ResultadoFalso({"id": params["id"]})


class BancoExtracaoFalso(BancoFalso):
    def __init__(self) -> None:
        super().__init__()
        self.transcricoes: dict[UUID, str | None] = {}
        self.rodadas_correcao: list[dict[str, Any]] = []
        # Quantas respostas já estavam gravadas quando cada submissão foi criada: o relógio que
        # ordena submissões e respostas neste banco falso.
        self.respostas_antes_da_submissao: dict[UUID, int] = {}

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[SessaoExtracaoFalsa]:
        yield SessaoExtracaoFalsa(self)
