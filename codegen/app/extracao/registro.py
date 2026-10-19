from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.extracao.construtos import condicao_limiar
from app.graph.prompts.extraction import INSTRUCOES_CONDICAO_LIMIAR
from app.tipos_estado import ValorRegra


@dataclass(frozen=True, slots=True)
class Construto:
    propriedades: dict[str, Any]
    obrigatorios: tuple[str, ...]
    instrucoes: str
    converter: Callable[[dict[str, Any]], dict[str, ValorRegra]]
    lastro_no_trecho: bool = False


CONSTRUTOS_HABILITADOS: dict[str, Construto] = {
    "condicao_limiar": Construto(
        propriedades=condicao_limiar.PROPRIEDADES,
        obrigatorios=condicao_limiar.OBRIGATORIOS,
        instrucoes=INSTRUCOES_CONDICAO_LIMIAR,
        converter=condicao_limiar.converter,
        lastro_no_trecho=True,
    ),
}
