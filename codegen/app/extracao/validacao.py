from functools import lru_cache
from pathlib import Path
from typing import Any

import simplejson
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as ErroSchema

from app.extracao.modelos import Rebaixamento
from app.representacao_regra import RepresentacaoRegra
from app.tipos_estado import ValorRegra


@lru_cache
def _validador_rebaixamentos() -> Draft202012Validator:
    caminho = (
        Path(__file__).resolve().parents[2] / "contracts/domain/rebaixamentos-extracao.schema.json"
    )
    return Draft202012Validator(simplejson.loads(caminho.read_text()))


def validar_conteudo(
    representacao: RepresentacaoRegra, rebaixamentos: list[Rebaixamento]
) -> tuple[dict[str, ValorRegra], list[dict[str, str]]]:
    validado: tuple[dict[str, ValorRegra], list[dict[str, str]]] | None = None
    try:
        regra = representacao.para_contrato()
        diagnosticos = [r.para_contrato() for r in rebaixamentos]
        _validador_rebaixamentos().validate(diagnosticos)
        elementos: Any = regra["especificacoes"]
        refs = [r["ref"] for r in diagnosticos]
        genericos = {e["ref"] for e in elementos if e["construto"] == "generico"}
        if len(refs) == len(set(refs)) and set(refs) == genericos:
            validado = regra, diagnosticos
    except (ValueError, TypeError, ErroSchema):
        pass
    if validado is None:
        raise ValueError("Resultado de extração inválido")
    return validado
