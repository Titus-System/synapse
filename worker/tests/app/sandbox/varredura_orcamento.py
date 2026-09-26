"""Varredura de orçamento dentro da imagem do sandbox (T-033).

Roda como script dentro do container (``python - < este arquivo``) e é importado pelos
testes, que o exercitam contra árvores de controle. Sem dependência além da stdlib: a
imagem só tem pandas e a biblioteca padrão.

A regra distingue **menção** de **valor**. ``resultado.py`` fala de orçamento em comentário
e docstring justamente para dizer que ele fica de fora, e um grep ingênuo acusaria isso.
O que é proibido é o orçamento existir como dado ou como símbolo do programa:

1. em arquivo de dados, nenhuma chave de objeto, em qualquer profundidade, é um termo;
2. em módulo Python, nenhum nome do programa (variável, argumento, atributo, função,
   classe, import) é um termo, e nenhuma string literal é *igual* a um termo — o que
   pegaria uma chave de dicionário sem pegar prosa;
3. no ambiente, nenhum nome nem valor de variável contém um termo.
"""

from __future__ import annotations

import ast
import json
import os
import unicodedata
from collections.abc import Iterator, Mapping
from pathlib import Path

TERMOS = frozenset({"orcamento", "budget"})


def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).casefold()


def e_termo(texto: str) -> bool:
    return normalizar(texto) in TERMOS


def contem_termo(texto: str) -> bool:
    normalizado = normalizar(texto)
    return any(termo in normalizado for termo in TERMOS)


def _chaves(valor: object, caminho: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(valor, dict):
        for chave, filho in valor.items():
            yield str(chave), f"{caminho}.{chave}"
            yield from _chaves(filho, f"{caminho}.{chave}")
    elif isinstance(valor, list):
        for indice, filho in enumerate(valor):
            yield from _chaves(filho, f"{caminho}[{indice}]")


def _documentos(caminho: Path) -> Iterator[tuple[int, object]]:
    """``.jsonl`` é um documento por linha; ``.json`` é um documento só, multilinha."""
    texto = caminho.read_text(encoding="utf-8")
    if caminho.suffix == ".json":
        yield 1, json.loads(texto)
        return
    for numero, linha in enumerate(texto.splitlines(), start=1):
        if linha.strip():
            yield numero, json.loads(linha)


def varrer_dados(raiz: Path) -> list[str]:
    achados: list[str] = []
    for caminho in sorted(raiz.rglob("*")):
        if caminho.suffix not in {".json", ".jsonl"} or not caminho.is_file():
            continue
        for numero, documento in _documentos(caminho):
            for chave, onde in _chaves(documento):
                if e_termo(chave):
                    achados.append(f"{caminho}, linha {numero}: chave {onde}")
    return achados


def _simbolos(arvore: ast.AST) -> Iterator[tuple[str, int]]:
    for no in ast.walk(arvore):
        match no:
            case ast.Name(id=nome) | ast.Attribute(attr=nome):
                yield nome, no.lineno
            case ast.arg(arg=nome):
                yield nome, no.lineno
            case ast.keyword(arg=str() as nome):
                yield nome, getattr(no, "lineno", 0)
            case (
                ast.FunctionDef(name=nome)
                | ast.AsyncFunctionDef(name=nome)
                | ast.ClassDef(name=nome)
            ):
                yield nome, no.lineno
            case ast.alias(name=nome, asname=apelido):
                yield apelido or nome.split(".")[-1], getattr(no, "lineno", 0)
            case ast.Constant(value=str() as texto):
                # Só a string que É o termo: chave de dicionário, não prosa.
                if e_termo(texto):
                    yield texto, no.lineno


def varrer_codigo(raiz: Path) -> list[str]:
    achados: list[str] = []
    for caminho in sorted(raiz.rglob("*.py")):
        arvore = ast.parse(caminho.read_text(encoding="utf-8"), filename=str(caminho))
        for nome, linha in _simbolos(arvore):
            if e_termo(nome):
                achados.append(f"{caminho}, linha {linha}: símbolo {nome!r}")
    return achados


def varrer_ambiente(ambiente: Mapping[str, str]) -> list[str]:
    return [
        f"variável de ambiente {nome}"
        for nome, valor in sorted(ambiente.items())
        if contem_termo(nome) or contem_termo(valor)
    ]


def varrer(dados: Path, codigo: Path, ambiente: Mapping[str, str]) -> list[str]:
    return varrer_dados(dados) + varrer_codigo(codigo) + varrer_ambiente(ambiente)


if __name__ == "__main__":
    print(json.dumps(varrer(Path("/app/sandbox"), Path("/app/app"), os.environ)))
