"""Alternativa determinística para uma regra que não coube no orçamento (US03, cenário 1).

O candidato sai de aritmética sobre os totais que o worker apurou, nunca de um modelo: a
LLM não produz número exibido nem veredito (AGENTS.md - Security). A simulação da
alternativa é que diz se ela cabe; aqui só se escolhe o que tentar.

A alternativa reduz todas as taxas da regra na mesma proporção - o percentual do núcleo, as
taxas por cargo e o efeito percentual de faixas e janelas de datas - e mantém o resto como
está: valores em reais, limiares, exclusões e o texto dos elementos genéricos. A primeira taxa
positiva é a referência: ela é estimada como se fosse a única taxa da regra, e as outras a
acompanham. Com a estrutura fixa, a comissão é uma parte que não depende das taxas mais um
múltiplo da referência, e é nessa reta que a estimativa, a sondagem e o refinamento andam.

São até `LIMITE_DE_TENTATIVAS` alternativas por job, cada uma simulada antes da seguinte: a
primeira de cada regra sai dos totais da simulação que não coube, e as outras refinam a
estimativa com as taxas já simuladas. Quando o orçamento não fica acima do baseline, os totais
não dão uma estimativa, e a primeira alternativa é uma sondagem que só serve para dar ao
refinamento o segundo ponto (T-283).
"""

from collections.abc import Iterator, Mapping, Sequence
from copy import deepcopy
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
#: A regra não tem taxa positiva a reduzir. A validação exige uma antes de qualquer simulação.
MOTIVO_NAO_SUPORTADA: Final = "nao_suportada"
#: As três taxas do job já foram simuladas e nenhuma coube: não há quarta tentativa.
MOTIVO_LIMITE: Final = "limite"

LIMITE_DE_TENTATIVAS: Final = 3

#: Como a taxa proposta foi obtida, para o log da proposta: conjunto fechado, sem a taxa.
METODO_ESTIMATIVA: Final = "estimativa"
METODO_SONDAGEM: Final = "sondagem"
METODO_REFINAMENTO: Final = "refinamento"

#: Elementos cujo efeito percentual é taxa da regra, o mesmo recorte que a tela exibe e que a
#: api confere. Efeito em reais, como o de um bônus por faixa, não é taxa.
CONSTRUTOS_COM_TAXA: Final = frozenset({"faixa_valor", "janela_datas"})
EFEITOS_PERCENTUAIS: Final = frozenset({"acrescimo_pct", "substituicao_pct"})


@dataclass(frozen=True, slots=True)
class Alternativa:
    """A proposta, ou a razão de não haver uma. `motivo` é o que entra na trilha."""

    motivo: str
    representacao: dict[str, ValorRegra] | None = None
    # Só na proposta.
    metodo: str | None = None
    taxas_ajustadas: int = 0


@dataclass(frozen=True, slots=True)
class TaxaSimulada:
    """A taxa de referência de uma versão já simulada no job, com a comissão que o worker apurou.

    As versões de uma cadeia têm as mesmas taxas na mesma proporção, então a referência basta
    para situar cada uma na reta da comissão.
    """

    percentual: Decimal
    simulado: Decimal


def percentual_que_cabe(
    percentual: Decimal, simulado: Decimal, orcamento: Decimal, *, baseline: Decimal
) -> Decimal | None:
    """Estima uma taxa conservadora como se ela fosse a única taxa da regra.

    O incremento sobre o baseline limita a parcela reduzível por proporcionalidade.
    A estimativa pode reduzir mais que o necessário quando já havia comissão no escopo, e menos
    quando a regra tem uma parte que não acompanha a taxa, como um bônus em reais; a simulação
    da candidata continua sendo a única confirmação de viabilidade.
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


def percentual_de_sondagem(
    percentual: Decimal, simulado: Decimal, orcamento: Decimal
) -> Decimal | None:
    """A primeira taxa quando o orçamento não fica acima do baseline.

    `percentual_que_cabe` supõe que a regra só soma às comissões de hoje, e aí nenhuma taxa
    caberia. Mas a regra substitui a taxa no seu escopo: a comissão é uma parte fixa, entre zero
    e o baseline, mais a taxa vezes as vendas no escopo. Com a parte fixa nesse intervalo, a taxa
    proporcional ao orçamento fica no máximo um `QUANTUM` abaixo da que cabe, pelo truncamento,
    então a sondagem não corta mais que o necessário. Simulada, ela é o segundo ponto da reta de
    `percentual_refinado`.
    """
    if percentual <= 0 or not 0 < orcamento < simulado:
        return None

    candidato = (percentual * orcamento / simulado).quantize(QUANTUM, rounding=ROUND_DOWN)
    if candidato <= 0 or candidato >= percentual:
        return None
    return candidato


def percentual_refinado(anteriores: Sequence[TaxaSimulada], orcamento: Decimal) -> Decimal | None:
    """Estima a taxa seguinte pela reta que passa pelas duas taxas simuladas mais próximas.

    Com a estrutura da regra fixa, a comissão é uma parte fixa mais a taxa de referência vezes
    um valor constante. Duas taxas simuladas dão essa reta sem supor que a parte fixa seja o
    baseline, e é onde ela cruza o orçamento que está a taxa seguinte. As duas de menor comissão
    são as mais próximas do orçamento, e uma taxa repetida conta uma vez.
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


def taxas(representacao: Mapping[str, ValorRegra]) -> list[Decimal]:
    """As taxas da regra, na ordem em que a alternativa as reduz e a api as confere."""
    encontradas: list[Decimal] = []
    for lugar, chave in _lugares_das_taxas(representacao):
        taxa = _numero(lugar[chave])
        if taxa is not None:
            encontradas.append(taxa)
    return encontradas


def taxa_de_referencia(representacao: Mapping[str, ValorRegra]) -> Decimal | None:
    """A primeira taxa positiva da regra.

    Cada taxa positiva continua positiva nas alternativas, e a estrutura não muda, então a
    referência fica na mesma posição em todas as versões de uma cadeia.
    """
    return next((taxa for taxa in taxas(representacao) if taxa > 0), None)


def propor_alternativa(
    representacao: Mapping[str, ValorRegra],
    simulado: Decimal,
    orcamento: Decimal,
    *,
    baseline: Decimal,
    anteriores: Sequence[TaxaSimulada] = (),
) -> Alternativa:
    """Monta a regra alternativa reduzindo todas as taxas na mesma proporção.

    `anteriores` são as taxas de referência já simuladas da regra e das versões que ela adapta.
    Com duas ou mais distintas, a referência é refinada por elas; com menos, ainda não há reta,
    e ela sai dos totais, como na primeira tentativa, ou da sondagem, quando o orçamento não
    fica acima do baseline e os totais não estimam. A representação proposta passa pela mesma
    verificação de coerência que barra uma regra na entrada: propor algo que já nasce inválido
    custaria um ciclo inteiro de simulação para terminar no mesmo lugar.
    """
    referencia = taxa_de_referencia(representacao)
    if referencia is None:
        return Alternativa(MOTIVO_NAO_SUPORTADA)

    if len({taxa.percentual for taxa in anteriores}) >= 2:
        metodo = METODO_REFINAMENTO
        candidato = percentual_refinado(anteriores, orcamento)
    else:
        metodo = METODO_ESTIMATIVA
        candidato = percentual_que_cabe(referencia, simulado, orcamento, baseline=baseline)
        if candidato is None and orcamento <= baseline:
            metodo = METODO_SONDAGEM
            candidato = percentual_de_sondagem(referencia, simulado, orcamento)
    # A api só aceita a proposta abaixo das taxas da versão de origem, que é a regra simulada.
    if candidato is None or candidato >= referencia:
        return Alternativa(MOTIVO_SEM_MARGEM)

    proposta = _reduzir_taxas(representacao, candidato, referencia)
    if proposta is None:
        return Alternativa(MOTIVO_SEM_MARGEM)
    if not verificar(proposta).liberado:
        return Alternativa(MOTIVO_INCOERENTE)
    ajustadas = sum(1 for taxa in taxas(proposta) if taxa != 0)
    return Alternativa(MOTIVO_PROPOSTA, proposta, metodo, ajustadas)


def _reduzir_taxas(
    representacao: Mapping[str, ValorRegra], candidato: Decimal, referencia: Decimal
) -> dict[str, ValorRegra] | None:
    """A regra com cada taxa multiplicada por `candidato / referencia`, truncada para zero.

    A referência vira exatamente o candidato. Taxa zero continua zero; uma taxa que zeraria
    tiraria parte da regra, e a api só aceita taxa que mantenha o sinal e diminua em módulo.
    """
    proposta: dict[str, ValorRegra] = {
        "nucleo": deepcopy(representacao.get("nucleo")),
        "especificacoes": deepcopy(representacao.get("especificacoes", [])),
    }
    for lugar, chave in _lugares_das_taxas(proposta):
        taxa = _numero(lugar[chave])
        if taxa is None or taxa == 0:
            continue
        reduzida = (taxa * candidato / referencia).quantize(QUANTUM, rounding=ROUND_DOWN)
        if reduzida * taxa <= 0 or abs(reduzida) >= abs(taxa):
            return None
        lugar[chave] = reduzida
    return proposta


def _lugares_das_taxas(
    representacao: Mapping[str, ValorRegra],
) -> Iterator[tuple[dict[str, ValorRegra], str]]:
    """Onde está cada taxa: núcleo, taxas por cargo na ordem da lista e efeitos percentuais."""
    nucleo = representacao.get("nucleo")
    if isinstance(nucleo, dict):
        if _numero(nucleo.get("percentual")) is not None:
            yield nucleo, "percentual"
        por_cargo = nucleo.get("taxas_por_cargo")
        if isinstance(por_cargo, list):
            for par in por_cargo:
                if isinstance(par, dict) and _numero(par.get("percentual")) is not None:
                    yield par, "percentual"
    especificacoes = representacao.get("especificacoes")
    if isinstance(especificacoes, list):
        for elemento in especificacoes:
            if (
                not isinstance(elemento, dict)
                or elemento.get("construto") not in CONSTRUTOS_COM_TAXA
            ):
                continue
            efeito = elemento.get("efeito")
            if (
                isinstance(efeito, dict)
                and efeito.get("tipo") in EFEITOS_PERCENTUAIS
                and _numero(efeito.get("valor")) is not None
            ):
                yield efeito, "valor"


def _numero(valor: ValorRegra) -> Decimal | None:
    if isinstance(valor, bool) or not isinstance(valor, Decimal | int):
        return None
    return Decimal(valor)
