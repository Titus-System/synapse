"""Alternativa determinística para uma regra que não coube no orçamento (US03, cenário 1).

O candidato sai de aritmética sobre os totais que o worker apurou, nunca de um modelo: a
LLM não produz número exibido nem veredito (AGENTS.md - Security). A simulação da
alternativa é que diz se ela cabe; aqui só se escolhe o que tentar.
"""

from collections.abc import Mapping
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


@dataclass(frozen=True, slots=True)
class Alternativa:
    """A proposta, ou a razão de não haver uma. `motivo` é o que entra na trilha."""

    motivo: str
    representacao: dict[str, ValorRegra] | None = None


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


def propor_alternativa(
    representacao: Mapping[str, ValorRegra],
    simulado: Decimal,
    orcamento: Decimal,
    *,
    baseline: Decimal,
) -> Alternativa:
    """Monta a regra alternativa mexendo só no percentual do núcleo.

    A representação proposta passa pela mesma verificação de coerência que barra uma regra
    na entrada: propor algo que já nasce inválido custaria um ciclo inteiro de simulação
    para terminar no mesmo lugar.
    """
    if representacao.get("especificacoes"):
        return Alternativa(MOTIVO_NAO_SUPORTADA)

    nucleo = representacao.get("nucleo")
    if not isinstance(nucleo, Mapping):
        return Alternativa(MOTIVO_SEM_MARGEM)

    percentual = nucleo.get("percentual")
    if isinstance(percentual, bool) or not isinstance(percentual, Decimal | int):
        return Alternativa(MOTIVO_SEM_MARGEM)

    candidato = percentual_que_cabe(Decimal(percentual), simulado, orcamento, baseline=baseline)
    if candidato is None:
        return Alternativa(MOTIVO_SEM_MARGEM)

    proposta: dict[str, ValorRegra] = {
        "nucleo": {**nucleo, "percentual": candidato},
        "especificacoes": representacao.get("especificacoes", []),
    }
    if not verificar(proposta).liberado:
        return Alternativa(MOTIVO_INCOERENTE)
    return Alternativa(MOTIVO_PROPOSTA, proposta)
