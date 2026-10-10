"""Confere os parâmetros da simulação já montados contra o contrato compartilhado.

Orçamento, meta de venda e período nunca fazem parte da regra (T-277): a extração os
devolve num objeto próprio, e este módulo só garante que esse objeto, depois de montado
por `motor.py`, continua respeitando `parametros-simulacao.schema.json` — do mesmo jeito
que `validacao.py` confere os rebaixamentos contra o schema deles.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from app.tipos_estado import ValorRegra


@lru_cache(maxsize=1)
def _validador_parametros() -> Draft202012Validator:
    diretorio = Path(__file__).resolve().parents[2] / "contracts" / "domain"
    esquemas = {
        caminho.name: json.loads(caminho.read_text(encoding="utf-8"))
        for caminho in diretorio.glob("*.schema.json")
    }
    registro = Registry().with_resources(
        (esquema["$id"], Resource.from_contents(esquema)) for esquema in esquemas.values()
    )
    return Draft202012Validator(
        esquemas["parametros-simulacao.schema.json"],
        registry=registro,
        format_checker=FormatChecker(),
    )


def validar_parametros(parametros: dict[str, Any]) -> dict[str, ValorRegra]:
    _validador_parametros().validate(parametros)
    return parametros
