import re
from decimal import Decimal
from typing import Any

from app.extracao.construto import Construto, ContextoExtracao
from app.extracao.efeito import SCHEMA_EFEITO, normalizar_efeito
from app.extracao.lastro import normalizar
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


# Outra condição, ou uma exceção, restringe quem recebe o efeito, e a faixa só representa o total
# vendido. "se", "caso" e "quando" ficam de fora porque introduzem a própria faixa.
_CONDICAO_ADICIONAL = re.compile(
    r"\b(?:desde que|condicionad[oa]s?|metas?|cotas?|atingimento|ticket|quantidade|exceto|salvo)\b"
)


def converter(rascunho: dict[str, Any], contexto: ContextoExtracao) -> dict[str, ValorRegra]:
    if _CONDICAO_ADICIONAL.search(normalizar(rascunho["trecho"])):
        raise ElementoRebaixadoError("termo_ambiguo")
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
        "uma faixa de loja ou marca, informe em campos o escopo e os limites. Condição além do "
        "total vendido ('desde que', meta, ticket) ou exceção ('exceto', 'salvo') permanece junto "
        "da faixa em um único generico, com o trecho completo; nunca converta essa faixa em "
        "pagamento incondicional."
    ),
    converter=converter,
)
