from copy import deepcopy
from typing import Any

from app.extracao.registro import CONSTRUTOS_HABILITADOS
from app.extracao.schema import NUCLEO, PARAMETROS, schema_saida


def schema_envelope_correcao() -> dict[str, Any]:
    # Lista vazia é a resposta a um texto que não pede mudança; exigir uma operação levaria o
    # modelo a inventar uma.
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["operacoes"],
        "properties": {"operacoes": {"type": "array"}},
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
    # O valor tem a forma do campo na extração inicial, com o trecho que lhe dá lastro. Uma lista
    # de códigos vazia tira o filtro, que passa a valer para todos.
    nucleo = {
        nome: (
            {chave: valor for chave, valor in campo.items() if chave != "minItems"}
            if nome in ("loja", "marca", "cargo")
            else campo
        )
        for nome, campo in NUCLEO["properties"].items()
    }
    parametros = PARAMETROS["properties"]
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
