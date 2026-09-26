"""Valida a saída do código gerado contra resultado-simulacao.schema.json.

Uso: py -3.12 validar-saida.py saida.json   (use - para ler do stdin)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

DIRETORIO_HARNESS = Path(__file__).resolve().parent
DIRETORIO_DOMAIN = DIRETORIO_HARNESS.parent / "domain"
ESQUEMA_RAIZ = "resultado-simulacao.schema.json"


def _carregar_registro() -> Registry:
    registro = Registry()
    for caminho in sorted(DIRETORIO_DOMAIN.glob("*.schema.json")):
        with caminho.open(encoding="utf-8") as arquivo:
            esquema = json.load(arquivo)
        recurso = Resource.from_contents(esquema, default_specification=DRAFT202012)
        registro = registro.with_resource(esquema["$id"], recurso)
    return registro


def _formatar_caminho(caminho: list[Any]) -> str:
    partes = ["$"]
    for parte in caminho:
        partes.append(f"[{parte}]" if isinstance(parte, int) else f".{parte}")
    return "".join(partes)


def validar_saida(saida: Any) -> list[str]:
    """Devolve os erros da saída contra o schema (lista vazia = válida)."""
    registro = _carregar_registro()
    esquema_raiz = json.loads((DIRETORIO_DOMAIN / ESQUEMA_RAIZ).read_text(encoding="utf-8"))
    validador = Draft202012Validator(
        esquema_raiz, registry=registro, format_checker=FormatChecker()
    )
    erros: list[str] = []
    for erro in sorted(
        validador.iter_errors(saida),
        key=lambda erro_validacao: tuple(str(parte) for parte in erro_validacao.absolute_path),
    ):
        erros.append(f"campo {_formatar_caminho(list(erro.absolute_path))}: {erro.message}")
    return erros


def _forcar_utf8() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            try:
                reconfigurar(encoding="utf-8")
            except (OSError, ValueError):
                pass


def _principal(argumentos: list[str]) -> int:
    _forcar_utf8()
    if len(argumentos) != 1:
        print("uso: validar-saida.py <arquivo.json | ->", file=sys.stderr)
        return 2

    origem = argumentos[0]
    try:
        texto = sys.stdin.read() if origem == "-" else Path(origem).read_text(encoding="utf-8")
        saida = json.loads(texto)
    except (OSError, json.JSONDecodeError) as erro:
        print(f"ERRO ao ler a saída: {erro}", file=sys.stderr)
        return 1

    erros = validar_saida(saida)
    if erros:
        print("Saída inválida:", file=sys.stderr)
        for erro in erros:
            print(f"- {erro}", file=sys.stderr)
        return 1

    print("Saída válida contra resultado-simulacao.schema.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_principal(sys.argv[1:]))
