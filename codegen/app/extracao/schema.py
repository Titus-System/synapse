from copy import deepcopy
from typing import Any

from app.extracao.registro import Construto

_TEXTO = {"type": "string", "minLength": 1}
_COMPETENCIA = {"type": "string", "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])$"}
_CODIGOS = {"type": "array", "minItems": 1, "items": _TEXTO}

NUCLEO: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "vigencia": {
            "type": "object",
            "additionalProperties": False,
            "required": ["inicio", "fim"],
            "properties": {"inicio": _COMPETENCIA, "fim": _COMPETENCIA},
        },
        "loja": _CODIGOS,
        "marca": _CODIGOS,
        "cargo": _CODIGOS,
        "percentual": {"type": "number"},
    },
}


def schema_elemento(construto: Construto | None = None) -> dict[str, Any]:
    propriedades = {"construto_pretendido": _TEXTO, "descricao": _TEXTO, "trecho": _TEXTO}
    obrigatorios = list(propriedades)
    if construto is not None:
        propriedades.update(construto.propriedades)
        obrigatorios.extend(construto.obrigatorios)
    return deepcopy(
        {
            "type": "object",
            "additionalProperties": False,
            "required": obrigatorios,
            "properties": propriedades,
        }
    )


def schema_envelope() -> dict[str, Any]:
    # Validação por elemento é separada para uma falha recuperável não perder os demais.
    return deepcopy(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["nucleo", "elementos"],
            "properties": {
                "nucleo": NUCLEO,
                "elementos": {"type": "array", "items": {"type": "object"}},
            },
        }
    )


def schema_saida(registro: dict[str, Construto]) -> dict[str, Any]:
    schema = schema_envelope()
    variantes = [schema_elemento()]
    for nome, construto in registro.items():
        variante = schema_elemento(construto)
        variante["properties"]["construto_pretendido"] = {"type": "string", "enum": [nome]}
        variantes.append(variante)
    schema["properties"]["elementos"]["items"] = (
        variantes[0] if len(variantes) == 1 else {"anyOf": variantes}
    )
    return schema
