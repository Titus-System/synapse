import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Self

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as ErroContrato
from pydantic import ConfigDict, RootModel, model_validator
from referencing import Registry, Resource

from app.tipos_estado import ValorRegra


@lru_cache(maxsize=1)
def _validador_regra() -> Draft202012Validator:
    # O build incorpora os contratos no artefato; runtime não acessa o monorepo.
    diretorio = Path(__file__).resolve().parents[1] / "contracts" / "domain"
    esquemas = [
        json.loads((diretorio / nome).read_text(encoding="utf-8"))
        for nome in (
            "representacao-regra.schema.json",
            "regra-nucleo.schema.json",
            "regra-especificacoes.schema.json",
            "comum.schema.json",
        )
    ]
    registro = Registry().with_resources(
        (esquema["$id"], Resource.from_contents(esquema)) for esquema in esquemas
    )
    return Draft202012Validator(esquemas[0], registry=registro, format_checker=FormatChecker())


def _valor_contrato(valor: ValorRegra) -> ValorRegra:
    if isinstance(valor, dict):
        return {chave: _valor_contrato(item) for chave, item in valor.items()}
    if isinstance(valor, list):
        return [_valor_contrato(item) for item in valor]
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


class RepresentacaoRegra(RootModel[dict[str, ValorRegra]]):
    """A própria estrutura da T-004, validada sem outro modelo de domínio."""

    model_config = ConfigDict(strict=True, allow_inf_nan=False, revalidate_instances="always")

    @model_validator(mode="after")
    def validar_contrato(self) -> Self:
        try:
            _validador_regra().validate(self.para_contrato())
        except ErroContrato as erro:
            # Não incluir conteúdo da regra na mensagem operacional da exceção.
            raise ValueError(f"Representação incompatível com T-004 em {erro.json_path}") from None
        return self

    def para_contrato(self) -> dict[str, ValorRegra]:
        # Decimal continua numérico; model_dump(mode="json") o converteria em string.
        return {chave: _valor_contrato(valor) for chave, valor in self.root.items()}
