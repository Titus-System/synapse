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

#: Granularidade do percentual proposto: 0,01 ponto percentual. Truncar para baixo, e não
#: arredondar, é o que mantém a proposta do lado de dentro do orçamento.
QUANTUM: Final = Decimal("0.0001")

MOTIVO_PROPOSTA: Final = "proposta"
MOTIVO_SEM_MARGEM: Final = "sem_margem"
MOTIVO_INCOERENTE: Final = "incoerente"


@dataclass(frozen=True, slots=True)
class Alternativa:
    """A proposta, ou a razão de não haver uma. `motivo` é o que entra na trilha."""

    motivo: str
    representacao: dict[str, ValorRegra] | None = None


def percentual_que_cabe(
    percentual: Decimal, simulado: Decimal, orcamento: Decimal
) -> Decimal | None:
    """Escala o percentual pela razão entre o orçamento e o total apurado.

    A proporção é exata quando todo o custo vem do percentual do núcleo; com elementos que
    somam valor fixo ela é uma aproximação, e por isso a alternativa é simulada de verdade
    antes de ser mostrada. Devolve `None` quando não há o que propor: sem total positivo não
    há razão a aplicar, e um percentual que zera ou que não desce não é alternativa.
    """
    if percentual <= 0 or simulado <= 0 or orcamento <= 0:
        return None

    candidato = (percentual * orcamento / simulado).quantize(QUANTUM, rounding=ROUND_DOWN)
    if candidato <= 0 or candidato >= percentual:
        return None
    return candidato


def propor_alternativa(
    representacao: Mapping[str, ValorRegra], simulado: Decimal, orcamento: Decimal
) -> Alternativa:
    """Monta a regra alternativa mexendo só no percentual do núcleo.

    A representação proposta passa pela mesma verificação de coerência que barra uma regra
    na entrada: propor algo que já nasce inválido custaria um ciclo inteiro de simulação
    para terminar no mesmo lugar.
    """
    nucleo = representacao.get("nucleo")
    if not isinstance(nucleo, Mapping):
        return Alternativa(MOTIVO_SEM_MARGEM)

    percentual = nucleo.get("percentual")
    if not isinstance(percentual, Decimal):
        return Alternativa(MOTIVO_SEM_MARGEM)

    candidato = percentual_que_cabe(percentual, simulado, orcamento)
    if candidato is None:
        return Alternativa(MOTIVO_SEM_MARGEM)

    proposta: dict[str, ValorRegra] = {
        "nucleo": {**nucleo, "percentual": candidato},
        "especificacoes": representacao.get("especificacoes", []),
    }
    if not verificar(proposta).liberado:
        return Alternativa(MOTIVO_INCOERENTE)
    return Alternativa(MOTIVO_PROPOSTA, proposta)
