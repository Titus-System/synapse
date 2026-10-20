import re
from typing import Any, cast

from app.extracao.construto import Construto, ContextoExtracao, com_lastro
from app.extracao.lastro import normalizar
from app.extracao.modelos import ElementoRebaixadoError
from app.extracao.vocabulario import CampoCodigo, FalhaCodigo, resolver_codigo
from app.tipos_estado import ValorRegra

# Um trecho por código, como no núcleo: sem um código no vocabulário, `resolver_codigo` usa os
# códigos que o trecho cita, e um trecho com vários códigos trocaria o desconhecido por outro.
_CODIGOS = {"type": "array", "minItems": 1, "items": com_lastro({"type": "string", "minLength": 1})}

# A dimensão não admite matrícula, e o número de uma matrícula pode coincidir com o código de uma
# loja: o trecho que fala de matrícula não chega à resolução de códigos.
_MATRICULA = re.compile(r"\bmatric(?:ulas?)?\b")
# Uma exceção que vem junto de um valor próprio restringe esse efeito, não a regra inteira, e o
# contrato só representa a exclusão da regra inteira.
_EFEITO_PROPRIO = re.compile(r"%|R\$")
_EFEITO_POR_EXTENSO = re.compile(r"\b(?:por cento|reais)\b")


def converter(rascunho: dict[str, Any], contexto: ContextoExtracao) -> dict[str, ValorRegra]:
    trecho: str = rascunho["trecho"]
    frase = normalizar(trecho)
    if _MATRICULA.search(frase):
        raise ValueError("Exclusão de matrícula")
    if _EFEITO_PROPRIO.search(trecho) or _EFEITO_POR_EXTENSO.search(frase):
        raise ElementoRebaixadoError("termo_ambiguo")

    dimensao = cast(CampoCodigo, rascunho["dimensao"])
    resolvidos: list[ValorRegra] = []
    falha: FalhaCodigo | None = None
    for campo in rascunho["valores"]:
        codigo, motivo = resolver_codigo(dimensao, campo["valor"], campo["trecho"], contexto.texto)
        if codigo is None:
            falha = falha or motivo
        elif codigo not in resolvidos:
            resolvidos.append(codigo)
    if falha is not None:
        # Excluir só os códigos resolvidos mudaria o resultado sem aviso; eles seguem no genérico
        # para a confirmação.
        campos: dict[str, ValorRegra] = {"dimensao": dimensao}
        if resolvidos:
            campos["valores"] = resolvidos
        raise ElementoRebaixadoError(falha, campos)
    return {"dimensao": dimensao, "valores": resolvidos}


EXCLUSAO = Construto(
    propriedades={
        "dimensao": {"type": "string", "enum": ["loja", "marca", "cargo"]},
        "valores": _CODIGOS,
    },
    obrigatorios=("dimensao", "valores"),
    instrucoes=(
        "exclusao: retira da regra inteira os códigos listados de uma dimensão (loja, marca ou "
        "cargo). Um elemento por dimensão: excluir um cargo e uma marca são dois elementos, na "
        "ordem do texto. valores é uma lista de {valor, trecho}, um por código, como loja/marca/"
        "cargo do núcleo: valor é o código ou o nome como o texto o diz ('150', 'gerente', "
        "'13'), mesmo fora do vocabulário, porque o motor confere e rebaixa; trecho é a parte "
        "literal do texto que cita só aquele código. O trecho do elemento é só a frase da "
        "exceção, e a descricao não acrescenta código que o trecho não diz. "
        "O código excluído nunca entra no núcleo: 'todas as lojas, menos a 13' deixa loja "
        "ausente do núcleo. 'Somente a loja 13' é núcleo, não exclusao. Se o texto inclui e "
        "exclui o mesmo código, extraia os dois como foram ditos, sem corrigir. "
        "Exemplos: 'Válido para todas as marcas e para todos os cargos, com exceção dos "
        "gerentes (150)' -> exclusao de cargo, valores [{valor:'150', trecho:'gerentes "
        "(150)'}], sem marca nem cargo no núcleo; 'Este bônus não se aplica aos cargos de "
        "gerente' -> exclusao de cargo, valores [{valor:'gerente', trecho:'gerente'}]; 'Para "
        "todas as lojas, exceto a 13 e a 58' -> exclusao de loja, valores [{valor:'13', "
        "trecho:'13'}, {valor:'58', trecho:'58'}]. "
        "É generico, com a frase literal inteira: exceção de matrícula ('exceto a matrícula "
        "MATRIC-422'); exceção que vale só para um efeito (um bônus em reais, um acréscimo, uma "
        "faixa) ou só para uma de várias regras do texto, mantida junto desse efeito ou regra em "
        "um único generico."
    ),
    converter=converter,
)
