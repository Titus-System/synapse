from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.tipos_estado import ValorRegra


@dataclass(frozen=True, slots=True)
class Construto:
    propriedades: dict[str, Any]
    obrigatorios: tuple[str, ...]
    instrucoes: str
    converter: Callable[[dict[str, Any]], dict[str, ValorRegra]]


CONSTRUTOS_HABILITADOS: dict[str, Construto] = {}
