import re
from typing import Any

from app.extracao.lastro import normalizar
from app.extracao.modelos import RebaixamentoConstrutoError
from app.tipos_estado import ValorRegra

PROPRIEDADES: dict[str, Any] = {
    "metrica": {"type": "string", "minLength": 1},
    "escopo_agregacao": {"type": "string", "minLength": 1},
    "operador": {"type": "string", "minLength": 1},
    "limiar": {"type": "number"},
}
# O rascunho pode omitir escopo; o contrato final não pode. A conversão preserva
# os outros três campos no genérico para que a omissão continue diagnosticável.
OBRIGATORIOS = ("metrica", "operador", "limiar")
_ESCOPOS = {
    "matricula": r"\b(?:venda individual|vendas individuais|por vendedor|por funcionario|"
    r"do vendedor|do funcionario|quem vender|quem vende|matricula)\b",
    "loja": r"\b(?:da loja|por loja|a loja vender|a loja vende)\b",
    "marca": r"\b(?:da marca|por marca|a marca vender|a marca vende)\b",
    "rede": r"\b(?:da empresa|da rede|por empresa|por rede|a empresa vender|a rede vender|"
    r"a empresa vende|a rede vende)\b",
}
# Nome do escopo como o modelo o devolve, sem a preposição das frases do texto.
_APELIDOS = {
    "matricula": {
        "matricula",
        "vendedor",
        "vendedores",
        "funcionario",
        "funcionarios",
        "individual",
    },
    "loja": {"loja", "lojas"},
    "marca": {"marca", "marcas"},
    "rede": {"rede", "empresa"},
}
_OPERADORES = {
    ">": r"\b(?:acima de|superior a|maior que|mais de)\b",
    ">=": r"\b(?:a partir de|no minimo|pelo menos)\b",
    "<": r"\b(?:abaixo de|menor que|menos de)\b",
    "<=": r"\b(?:ate|no maximo)\b",
    "==": r"\bigual a\b",
}
_METRICA_NAO_SUPORTADA = re.compile(
    r"\b(?:meta|metas|cota|cotas|quantidade|quantidades|ticket|atingimento|unidades)\b"
)
_ELEMENTO_RESTRITO = re.compile(r"\b(?:bonus|premio|adicional|acrescimo|faixa)\b")
_AMBIGUIDADE = re.compile(r"\b(?:cerca de|perto de|aproximadamente|em torno de|se e somente se)\b")
# Negação e exclusão invertem o sentido do operador, que o conversor só lê pelo termo positivo.
_NEGACAO = re.compile(r"\b(?:nao|nunca|nem|sem|exceto|salvo|ninguem|demais)\b")


def converter(elemento: dict[str, Any]) -> dict[str, ValorRegra]:
    trecho = elemento["trecho"]
    texto = normalizar(trecho)
    if (
        normalizar(elemento["metrica"]) not in ("venda_total", "venda total")
        or not re.search(r"\b(?:venda|vendas|vender|vende)\b", texto)
        or _METRICA_NAO_SUPORTADA.search(texto)
        or _ELEMENTO_RESTRITO.search(texto)
        or _AMBIGUIDADE.search(texto)
        or _NEGACAO.search(texto)
    ):
        raise RebaixamentoConstrutoError("termo_ambiguo")

    operadores = {op for op, padrao in _OPERADORES.items() if re.search(padrao, texto)}
    operadores.update(re.findall(r">=|<=|==|>|<", trecho))
    if len(operadores) != 1:
        raise RebaixamentoConstrutoError("termo_ambiguo")
    operador = operadores.pop()
    informado = elemento["operador"]
    if informado != operador and not re.fullmatch(_OPERADORES[operador], normalizar(informado)):
        raise RebaixamentoConstrutoError("termo_ambiguo")

    campos: dict[str, ValorRegra] = {
        "metrica": "venda_total",
        "operador": operador,
        "limiar": elemento["limiar"],
    }
    escopos = {escopo for escopo, padrao in _ESCOPOS.items() if re.search(padrao, texto)}
    if not escopos:
        raise RebaixamentoConstrutoError("campo_obrigatorio_ausente", campos)
    if len(escopos) != 1:
        raise RebaixamentoConstrutoError("termo_ambiguo", campos)
    escopo = escopos.pop()
    informado = elemento.get("escopo_agregacao")
    if informado is not None and informado != escopo:
        nome = normalizar(informado)
        aliases = {s for s, padrao in _ESCOPOS.items() if re.search(padrao, nome)}
        aliases.update(s for s, nomes in _APELIDOS.items() if nome in nomes)
        if aliases != {escopo}:
            raise RebaixamentoConstrutoError("termo_ambiguo", campos)
    return {**campos, "escopo_agregacao": escopo}
