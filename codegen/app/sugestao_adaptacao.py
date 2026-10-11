"""Alternativa determinística para uma regra que não coube no orçamento (US03, cenário 1).

O candidato sai de aritmética sobre os totais que o worker apurou, nunca de um modelo: a
LLM não produz número exibido nem veredito (AGENTS.md - Security). A simulação da
alternativa é que diz se ela cabe; aqui só se escolhe o que tentar.

São até `LIMITE_DE_TENTATIVAS` taxas por job, cada uma simulada antes da seguinte: a primeira
de cada regra sai dos totais da simulação que não coube, e as outras refinam a estimativa com
as taxas já simuladas.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Final

from app.nos.validacao_dominio import verificar
from app.tipos_estado import ValorRegra

#: Granularidade: 0,01 ponto percentual. Truncar evita elevar a taxa calculada;
#: só a simulação da alternativa confirma se o custo cabe no orçamento.
QUANTUM: Final = Decimal("0.0001")

MOTIVO_PROPOSTA: Final = "proposta"
MOTIVO_SEM_MARGEM: Final = "sem_margem"
MOTIVO_INCOERENTE: Final = "incoerente"
MOTIVO_NAO_SUPORTADA: Final = "nao_suportada"
#: As três taxas do job já foram simuladas e nenhuma coube: não há quarta tentativa.
MOTIVO_LIMITE: Final = "limite"

LIMITE_DE_TENTATIVAS: Final = 3


@dataclass(frozen=True, slots=True)
class Alternativa:
    """A proposta, ou a razão de não haver uma. `motivo` é o que entra na trilha."""

    motivo: str
    representacao: dict[str, ValorRegra] | None = None


@dataclass(frozen=True, slots=True)
class TaxaSimulada:
    """Uma taxa do núcleo já simulada no job, com a comissão que o worker apurou para ela."""

    percentual: Decimal
    simulado: Decimal


def percentual_que_cabe(
    percentual: Decimal, simulado: Decimal, orcamento: Decimal, *, baseline: Decimal
) -> Decimal | None:
    """Estima uma taxa conservadora para uma regra percentual simples.

    O incremento sobre o baseline limita a parcela reduzível por proporcionalidade.
    A estimativa pode reduzir mais que o necessário quando já havia comissão no escopo;
    a simulação da candidata continua sendo a única confirmação de viabilidade.
    Fora de baseline < orçamento < simulado não estimamos: isso não prova que inexiste solução.
    """
    if percentual <= 0 or baseline < 0 or not baseline < orcamento < simulado:
        return None

    candidato = (percentual * (orcamento - baseline) / (simulado - baseline)).quantize(
        QUANTUM, rounding=ROUND_DOWN
    )
    if candidato <= 0 or candidato >= percentual:
        return None
    return candidato


def percentual_refinado(anteriores: Sequence[TaxaSimulada], orcamento: Decimal) -> Decimal | None:
    """Estima a taxa seguinte pela reta que passa pelas duas taxas simuladas mais próximas.

    Numa regra só de núcleo, a comissão é uma parte fixa mais a taxa vezes as vendas no
    escopo. Duas taxas simuladas dão essa reta sem supor que a parte fixa seja o baseline, e é
    onde ela cruza o orçamento que está a taxa seguinte. As duas de menor comissão são as mais
    próximas do orçamento, e uma taxa repetida conta uma vez.
    Sem duas taxas distintas, ou sem uma reta que desça até o orçamento abaixo da menor taxa já
    simulada, não estimamos.
    """
    comissao_por_taxa = {taxa.percentual: taxa.simulado for taxa in anteriores}
    if len(comissao_por_taxa) < 2:
        return None

    (mais_proxima, comissao), (seguinte, comissao_seguinte) = sorted(
        comissao_por_taxa.items(), key=lambda par: par[1]
    )[:2]
    inclinacao = (comissao_seguinte - comissao) / (seguinte - mais_proxima)
    if inclinacao <= 0:
        return None

    candidato = (mais_proxima + (orcamento - comissao) / inclinacao).quantize(
        QUANTUM, rounding=ROUND_DOWN
    )
    if candidato <= 0 or candidato >= min(comissao_por_taxa):
        return None
    return candidato


def propor_alternativa(
    representacao: Mapping[str, ValorRegra],
    simulado: Decimal,
    orcamento: Decimal,
    *,
    baseline: Decimal,
    anteriores: Sequence[TaxaSimulada] = (),
) -> Alternativa:
    """Monta a regra alternativa mexendo só no percentual do núcleo.

    `anteriores` são as taxas já simuladas da regra e das versões que ela adapta. Com duas ou
    mais distintas, a taxa é refinada por elas; com menos, ainda não há reta, e a taxa sai dos
    totais, como na primeira tentativa. A representação proposta passa pela mesma verificação
    de coerência que barra uma regra na entrada: propor algo que já nasce inválido custaria um
    ciclo inteiro de simulação para terminar no mesmo lugar.
    """
    if representacao.get("especificacoes"):
        return Alternativa(MOTIVO_NAO_SUPORTADA)

    nucleo = representacao.get("nucleo")
    if not isinstance(nucleo, Mapping):
        return Alternativa(MOTIVO_SEM_MARGEM)

    percentual = nucleo.get("percentual")
    if isinstance(percentual, bool) or not isinstance(percentual, Decimal | int):
        return Alternativa(MOTIVO_SEM_MARGEM)

    if len({taxa.percentual for taxa in anteriores}) >= 2:
        candidato = percentual_refinado(anteriores, orcamento)
    else:
        candidato = percentual_que_cabe(Decimal(percentual), simulado, orcamento, baseline=baseline)
    # A api só aceita a proposta abaixo da taxa da versão de origem, que é a regra simulada.
    if candidato is None or candidato >= percentual:
        return Alternativa(MOTIVO_SEM_MARGEM)

    proposta: dict[str, ValorRegra] = {
        "nucleo": {**nucleo, "percentual": candidato},
        "especificacoes": representacao.get("especificacoes", []),
    }
    if not verificar(proposta).liberado:
        return Alternativa(MOTIVO_INCOERENTE)
    return Alternativa(MOTIVO_PROPOSTA, proposta)
