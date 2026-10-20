from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.tipos_estado import ValorRegra


@dataclass(frozen=True, slots=True)
class ContextoExtracao:
    texto: str
    competencias: Sequence[str]


@dataclass(frozen=True, slots=True)
class Construto:
    propriedades: dict[str, Any]
    obrigatorios: tuple[str, ...]
    instrucoes: str
    converter: Callable[[dict[str, Any], ContextoExtracao], dict[str, ValorRegra]]
    lastro_no_trecho: bool = False


def com_lastro(valor: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["valor", "trecho"],
        "properties": {"valor": valor, "trecho": {"type": "string", "minLength": 1}},
    }
