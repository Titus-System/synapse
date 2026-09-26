from functools import lru_cache
from pathlib import Path

import simplejson
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as ErroSchema
from referencing import Registry, Resource


class ContratoError(ValueError):
    pass


@lru_cache
def validador(nome: str) -> Draft202012Validator:
    diretorio = Path(__file__).resolve().parents[2] / "contracts"
    esquemas = {
        arquivo.relative_to(diretorio).as_posix(): simplejson.loads(
            arquivo.read_text(encoding="utf-8"), use_decimal=True
        )
        for arquivo in diretorio.rglob("*.schema.json")
    }
    registro = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in esquemas.values()
    )
    return Draft202012Validator(
        esquemas[f"events/{nome}.schema.json"], registry=registro, format_checker=FormatChecker()
    )


def validar(nome: str, payload: object) -> None:
    try:
        validador(nome).validate(payload)
    except ErroSchema:
        raise ContratoError("Mensagem incompatível com o contrato") from None
