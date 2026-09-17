import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Self

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as ErroContrato
from pydantic import (
    ConfigDict,
    ModelWrapValidatorHandler,
    RootModel,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic_core import PydanticCustomError
from referencing import Registry, Resource

from app.tipos_estado import ValorRegra

_ESTRUTURA = TypeAdapter(dict[str, ValorRegra], config=ConfigDict(allow_inf_nan=False))


def _erro_representacao() -> ValidationError:
    # Ocultar a impressão não basta: errors()/json() também não podem reter a regra.
    return ValidationError.from_exception_data(
        "RepresentacaoRegra",
        [
            {
                "type": PydanticCustomError(
                    "representacao_regra", "Representação incompatível com T-004"
                ),
                "loc": (),
                "input": None,
            }
        ],
        hide_input=True,
    )


@lru_cache(maxsize=1)
def _validador_regra() -> Draft202012Validator:
    # O build incorpora os contratos no artefato; runtime não acessa o monorepo.
    diretorio = Path(__file__).resolve().parents[1] / "contracts" / "domain"
    esquemas = {
        caminho.name: json.loads(caminho.read_text(encoding="utf-8"))
        for caminho in diretorio.glob("*.schema.json")
    }
    registro = Registry().with_resources(
        (esquema["$id"], Resource.from_contents(esquema)) for esquema in esquemas.values()
    )
    return Draft202012Validator(
        esquemas["representacao-regra.schema.json"],
        registry=registro,
        format_checker=FormatChecker(),
    )


def _valor_contrato(valor: ValorRegra) -> ValorRegra:
    if isinstance(valor, dict):
        return {chave: _valor_contrato(item) for chave, item in valor.items()}
    if isinstance(valor, list):
        return [_valor_contrato(item) for item in valor]
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def _converter_e_validar(raiz: object) -> dict[str, ValorRegra]:
    try:
        estrutura = _ESTRUTURA.validate_python(raiz, strict=True)
        # Decimal continua numérico; model_dump(mode="json") o converteria em string.
        contrato = {chave: _valor_contrato(valor) for chave, valor in estrutura.items()}
        _validador_regra().validate(contrato)
    except (ValidationError, ErroContrato):
        raise _erro_representacao() from None
    return contrato


class RepresentacaoRegra(RootModel[dict[str, ValorRegra]]):
    """A própria estrutura da T-004, validada sem outro modelo de domínio."""

    model_config = ConfigDict(
        strict=True, allow_inf_nan=False, revalidate_instances="always", hide_input_in_errors=True
    )

    @model_validator(mode="wrap")
    @classmethod
    def validar_contrato(cls, valor: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        try:
            _converter_e_validar(valor.root if isinstance(valor, cls) else valor)
            return handler(valor)
        except ValidationError:
            raise _erro_representacao() from None

    def para_contrato(self) -> dict[str, ValorRegra]:
        return _converter_e_validar(self.root)
