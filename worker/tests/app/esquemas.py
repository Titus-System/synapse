"""Valida mensagens contra os schemas de `contracts/` (eventos e domínio), como o codegen faz.

O schema é o contrato público que a api e o codegen leem: um evento que o worker produz e que
ele não valida é um evento que o outro lado pode recusar.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


@lru_cache
def _esquemas() -> dict[str, Any]:
    return {
        arquivo.relative_to(CONTRACTS).as_posix(): json.loads(arquivo.read_text(encoding="utf-8"))
        for arquivo in CONTRACTS.rglob("*.schema.json")
    }


@lru_cache
def _validador(caminho: str) -> Draft202012Validator:
    esquemas = _esquemas()
    registro: Registry[Any] = Registry().with_resources(
        (e["$id"], Resource.from_contents(e, default_specification=DRAFT202012))
        for e in esquemas.values()
    )
    return Draft202012Validator(
        esquemas[caminho], registry=registro, format_checker=FormatChecker()
    )


def erros_do_evento(nome: str, corpo: object) -> list[str]:
    """Os erros de `corpo` contra `contracts/events/<nome>.schema.json` (vazio = válido)."""
    validador = _validador(f"events/{nome}.schema.json")
    return [
        f"{'/'.join(str(p) for p in erro.absolute_path) or '$'}: {erro.message}"
        for erro in validador.iter_errors(corpo)
    ]


def erros_do_log(registro: object) -> list[str]:
    """Os erros de uma linha de log contra `contracts/observability/log.schema.json`."""
    validador = _validador("observability/log.schema.json")
    return [erro.message for erro in validador.iter_errors(registro)]
