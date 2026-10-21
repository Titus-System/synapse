"""Vocabulário versionado no pacote, sem leitura do dataset em runtime."""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

from app.extracao.lastro import normalizar, trecho_literal

type CampoCodigo = Literal["loja", "marca", "cargo"]
type FalhaCodigo = Literal["codigo_fora_do_vocabulario", "termo_ambiguo", "valor_sem_lastro"]


@lru_cache(maxsize=1)
def carregar_vocabulario() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(Path(__file__).with_name("vocabulario.json").read_text(encoding="utf-8")),
    )


def _formas_cargo(nome: str) -> set[str]:
    return {nome, nome + "s", nome + "es" if nome.endswith("r") else nome + "s"}


def _candidatos(campo: CampoCodigo, termo: str) -> set[str]:
    descricoes: dict[str, list[str]] = carregar_vocabulario()[campo]
    nome = normalizar(termo)
    encontrados = {
        codigo
        for codigo, nomes in descricoes.items()
        if any(nome == normalizar(descricao) for descricao in nomes)
    }
    if encontrados or campo != "cargo":
        return encontrados
    return {
        codigo
        for codigo, nomes in descricoes.items()
        if any(nome in _formas_cargo(normalizar(descricao).split()[0]) for descricao in nomes)
    }


def _codigos_presentes(campo: CampoCodigo, trecho: str) -> set[str]:
    descricoes: dict[str, list[str]] = carregar_vocabulario()[campo]
    texto = normalizar(trecho)
    encontrados: set[str] = set()
    for codigo, nomes in descricoes.items():
        if re.search(rf"(?<!\d){re.escape(codigo)}(?!\d)", trecho):
            encontrados.add(codigo)
        if any(re.search(rf"\b{re.escape(normalizar(nome))}\b", texto) for nome in nomes):
            encontrados.add(codigo)
        if campo == "cargo":
            for nome in nomes:
                primeiro = normalizar(nome).split()[0]
                if any(
                    re.search(rf"\b{re.escape(forma)}\b", texto)
                    for forma in _formas_cargo(primeiro)
                ):
                    encontrados.add(codigo)
    return encontrados


def resolver_codigo(
    campo: CampoCodigo,
    termo: str,
    trecho: object,
    texto: str,
    *,
    exigir_termo_conhecido: bool = False,
) -> tuple[str | None, FalhaCodigo | None]:
    if not trecho_literal(texto, trecho):
        return None, "valor_sem_lastro"
    assert isinstance(trecho, str)
    codigos: dict[str, list[str]] = carregar_vocabulario()[campo]
    informado = normalizar(termo)
    candidatos = {informado} if informado in codigos else _candidatos(campo, termo)
    evidenciados = _codigos_presentes(campo, trecho)
    if not candidatos and not exigir_termo_conhecido:
        candidatos = evidenciados
    if not candidatos:
        return None, "codigo_fora_do_vocabulario"
    verificaveis = candidatos & evidenciados
    if not verificaveis:
        return None, "valor_sem_lastro" if candidatos else "codigo_fora_do_vocabulario"
    if len(verificaveis) > 1:
        return None, "termo_ambiguo"
    return next(iter(verificaveis)), None
