import re
from decimal import Decimal
from typing import Any

from app.extracao.construto import Construto, ContextoExtracao
from app.extracao.efeito import SCHEMA_EFEITO, normalizar_efeito
from app.extracao.modelos import ElementoRebaixadoError
from app.tipos_estado import ValorRegra

# O contrato exige `limite_superior`, e o JSON não tem infinito. Um bilhão de reais está acima de
# qualquer total do dataset (o maior mês vende R$ 18,68 milhões), então a faixa aberta o usa.
LIMITE_SUPERIOR_ABERTO = Decimal("1000000000")

_ABERTURA = re.compile(
    r"\b(?:acima|a\s+partir|mais\s+de|superior|maior|ou\s+mais|em\s+diante|"
    r"no\s+m[ií]nimo|pelo\s+menos)\b",
    re.IGNORECASE,
)


def converter(rascunho: dict[str, Any], contexto: ContextoExtracao) -> dict[str, ValorRegra]:
    efeito = normalizar_efeito(rascunho["efeito"], contexto.texto)
    if rascunho["faixa_aberta"]:
        if "limite_superior" in rascunho:
            raise ValueError("Faixa aberta com limite superior")
        # Sem uma palavra de abertura no trecho, o limite superior ausente é campo que faltou.
        if not _ABERTURA.search(rascunho["trecho"]):
            raise ElementoRebaixadoError("campo_obrigatorio_ausente")
        limite_superior = LIMITE_SUPERIOR_ABERTO
    else:
        limite_superior = rascunho["limite_superior"]
    return {
        "limite_inferior": rascunho["limite_inferior"],
        "limite_superior": limite_superior,
        "efeito": efeito,
    }


FAIXA_VALOR = Construto(
    propriedades={
        "limite_inferior": {"type": "number"},
        "limite_superior": {"type": "number"},
        "faixa_aberta": {"type": "boolean"},
        "efeito": SCHEMA_EFEITO,
    },
    obrigatorios=("limite_inferior", "faixa_aberta", "efeito"),
    instrucoes=(
        "faixa_valor: faixa de venda individual do colaborador no mês, com efeito próprio. Cada "
        "faixa é um elemento, na ordem do texto; os limites saem como o texto os diz, sem "
        "preencher lacunas. limite_inferior e limite_superior são {valor, trecho} em reais; "
        "numa faixa aberta ('acima de R$ 60.001') use faixa_aberta true e omita "
        "limite_superior. 'Acima de R$ 40 mil, bônus de R$ 3.500' é uma faixa aberta, não um "
        "limiar. O trecho cobre os limites e o efeito da faixa. efeito: tipo bonus_fixo (reais), "
        "acrescimo_pct ou substituicao_pct. Venda total de loja ou de marca, quantidade, ticket, "
        "atingimento de meta e faixa sem efeito identificável são generico; no generico de "
        "uma faixa de loja ou marca, informe em campos o escopo e os limites."
    ),
    converter=converter,
)
