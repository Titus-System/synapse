from copy import deepcopy
from typing import Any

from app.extracao.registro import CONSTRUTOS_HABILITADOS
from app.extracao.schema import NUCLEO, PARAMETROS, schema_saida


def schema_envelope_correcao() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["operacoes"],
        "properties": {"operacoes": {"type": "array", "minItems": 1}},
    }


def _operacao(tipo: str, **campos: Any) -> dict[str, Any]:
    propriedades = {"tipo": {"const": tipo}, **campos}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(propriedades),
        "properties": propriedades,
    }


def _definir(tipo: str, campos: dict[str, Any]) -> dict[str, Any]:
    operacao = _operacao(tipo, campo={"enum": list(campos)}, valor={})
    operacao["anyOf"] = [
        {"properties": {"campo": {"const": nome}, "valor": schema}}
        for nome, schema in campos.items()
    ]
    return operacao


def schema_operacao_correcao(*, validar_elemento: bool = True) -> dict[str, Any]:
    nucleo = {}
    for nome, campo in NUCLEO["properties"].items():
        if nome in ("loja", "marca", "cargo"):
            nucleo[nome] = {"type": "array", "items": campo["items"]["properties"]["valor"]}
        else:
            nucleo[nome] = campo["properties"]["valor"]
    parametros = {
        nome: campo["properties"]["valor"] for nome, campo in PARAMETROS["properties"].items()
    }
    elemento = (
        schema_saida(CONSTRUTOS_HABILITADOS)["properties"]["elementos"]["items"]
        if validar_elemento
        else {"type": "object"}
    )
    ref = {"type": "string", "pattern": r"^elem\.[0-9]+$"}
    return deepcopy(
        {
            "anyOf": [
                _definir("definir_nucleo", nucleo),
                _operacao("substituir_elemento", ref=ref, elemento=elemento),
                _operacao("remover_elemento", ref=ref),
                _operacao("adicionar_elemento", elemento=elemento),
                _definir("definir_parametro", parametros),
                _operacao("remover_parametro", campo={"enum": list(parametros)}),
            ]
        }
    )


def schema_operacoes_correcao() -> dict[str, Any]:
    """Schema fechado para a saída do modelo; recuperação por item ocorre no motor."""
    schema = schema_envelope_correcao()
    schema["properties"]["operacoes"]["items"] = schema_operacao_correcao()
    return schema
