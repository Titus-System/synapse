from copy import deepcopy
from typing import Any

from app.extracao.registro import Construto

_TEXTO = {"type": "string", "minLength": 1}
_COMPETENCIA = {"type": "string", "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])$"}
_CODIGOS = {"type": "array", "minItems": 1, "items": _TEXTO}
_MONETARIO = {"type": "number"}


def _schema_parametro(valor: dict[str, Any]) -> dict[str, Any]:
    # O trecho só serve à conferência de lastro da T-210; até lá, o valor entra como o
    # modelo o devolveu, sem checar o trecho contra o texto.
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["valor", "trecho"],
        "properties": {"valor": valor, "trecho": _TEXTO},
    }


PARAMETROS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "orcamento": _schema_parametro(_MONETARIO),
        "meta_venda": _schema_parametro(_MONETARIO),
        "competencias": _schema_parametro({"type": "array", "minItems": 1, "items": _COMPETENCIA}),
    },
}

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
            "required": ["nucleo", "elementos", "parametros"],
            # O modelo gera as chaves na ordem de `properties`. Decidindo os parâmetros antes dos
            # elementos, ele não faz do pedido de simular um período um elemento.
            "properties": {
                "nucleo": NUCLEO,
                "parametros": PARAMETROS,
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
