from copy import deepcopy
from typing import Any

from app.extracao.construto import Construto, com_lastro

_TEXTO = {"type": "string", "minLength": 1}
_COMPETENCIA = {"type": "string", "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])$"}


_CODIGOS = {"type": "array", "minItems": 1, "items": com_lastro(_TEXTO)}
_ESCOPO = {"anyOf": [_CODIGOS, com_lastro({"type": "array", "maxItems": 0})]}
_MONETARIO = {"type": "number"}
TAXA_POR_CARGO = com_lastro(
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["cargo", "percentual"],
        "properties": {"cargo": _TEXTO, "percentual": {"type": "number"}},
    }
)


def _schema_parametro(valor: dict[str, Any]) -> dict[str, Any]:
    return com_lastro(valor)


PARAMETROS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "orcamento": _schema_parametro(_MONETARIO),
        "meta_venda": _schema_parametro(_MONETARIO),
        "competencias": {
            **_schema_parametro({"type": "array", "minItems": 1, "items": _COMPETENCIA}),
            "description": (
                "Período que o texto manda simular ou liga ao orçamento ou à meta, como "
                "'simular de setembro a novembro'. Não é a vigência da comissão."
            ),
        },
    },
}

NUCLEO: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "vigencia": {
            **com_lastro(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["inicio", "fim"],
                    "properties": {"inicio": _COMPETENCIA, "fim": _COMPETENCIA},
                }
            ),
            "description": (
                "Quando a comissão vale. Nunca é o período a simular nem as competências "
                "publicadas."
            ),
        },
        "loja": _ESCOPO,
        "marca": _ESCOPO,
        "cargo": _ESCOPO,
        "percentual": com_lastro({"type": "number"}),
        "taxas_por_cargo": {"type": "array", "minItems": 1, "items": TAXA_POR_CARGO},
    },
}


# Com um construto habilitado, o elemento passa a ser um `anyOf`, e sem esta descrição o modelo
# deixa de criar o genérico para o que o núcleo não comporta.
_DESCRICAO_GENERICO = (
    "Qualquer condição ou efeito da regra que nenhum outro construto representa. O núcleo só "
    "tem vigência, loja, marca, cargo, percentual e taxas por cargo: qualquer outra condição, "
    "como uma base "
    "de cálculo diferente ('sobre a venda total da loja'), é elemento com "
    "construto_pretendido 'generico'. Nunca descarte."
)


def schema_elemento(construto: Construto | None = None) -> dict[str, Any]:
    propriedades = {"construto_pretendido": _TEXTO, "descricao": _TEXTO, "trecho": _TEXTO}
    obrigatorios = list(propriedades)
    if construto is not None:
        propriedades.update(
            {
                nome: (
                    com_lastro(definicao)
                    if definicao.get("type") in ("number", "integer")
                    else definicao
                )
                for nome, definicao in construto.propriedades.items()
            }
        )
        obrigatorios.extend(construto.obrigatorios)
    return deepcopy(
        {
            "type": "object",
            "additionalProperties": False,
            "required": obrigatorios,
            "properties": propriedades,
        }
    )


def schema_envelope() -> dict[str, Any]:
    # Validação por elemento é separada para uma falha recuperável não perder os demais.
    return deepcopy(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["nucleo", "elementos", "parametros"],
            # O modelo gera as chaves na ordem de `properties`. Decidindo os parâmetros antes dos
            # elementos, ele não faz do pedido de simular um período um elemento.
            "properties": {
                "nucleo": NUCLEO,
                "parametros": PARAMETROS,
                "elementos": {"type": "array", "items": {"type": "object"}},
            },
        }
    )


def schema_saida(registro: dict[str, Construto]) -> dict[str, Any]:
    schema = schema_envelope()
    variantes = [{**schema_elemento(), "description": _DESCRICAO_GENERICO}]
    for nome, construto in registro.items():
        variante = schema_elemento(construto)
        variante["properties"]["construto_pretendido"] = {"type": "string", "enum": [nome]}
        variantes.append(variante)
    schema["properties"]["elementos"]["items"] = (
        variantes[0] if len(variantes) == 1 else {"anyOf": variantes}
    )
    return schema
