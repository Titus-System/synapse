"""Alternativa determinística para uma regra que não coube no orçamento (US03, cenário 1).

O candidato sai de aritmética sobre o resultado que o worker apurou, nunca de um modelo: a
LLM não produz número exibido nem veredito (AGENTS.md - Security). A simulação da
alternativa é que diz se ela cabe; aqui só se escolhe o que tentar.

A alternativa reduz todas as taxas da regra na mesma proporção - o percentual do núcleo, as
taxas por cargo e o efeito percentual de faixas e janelas de datas - e mantém o resto como
está: valores em reais, limiares, exclusões e o texto dos elementos genéricos. A primeira taxa
positiva é a referência: ela é estimada como se fosse a única taxa da regra, e as outras a
acompanham. Com a estrutura fixa, a comissão é uma parte que não depende das taxas mais um
múltiplo da referência, e é nessa reta que a estimativa e o refinamento andam.

São até `LIMITE_DE_TENTATIVAS` alternativas por job, cada uma simulada antes da seguinte: a
primeira de cada regra sai da simulação que não coube, com a comissão das linhas que a regra não
alcança como parte fixa, e as outras refinam a estimativa com as taxas já simuladas. A parte
fixa nunca é maior que a verdadeira, então a primeira taxa nunca fica abaixo da que cabe: uma
alternativa que cabe encerra a iteração, e uma estimativa baixa demais seria a sugestão final.
"""

from collections.abc import Iterator, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Final

from app.alcance_regra import AlcanceDaRegra
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
    percentual: Decimal, simulado: Decimal, orcamento: Decimal, *, parte_fixa: Decimal
) -> Decimal | None:
    """A taxa em que a reta da comissão cruza o orçamento, como se fosse a única taxa da regra.

    A regra substitui a taxa no seu escopo, então a comissão é uma parte que nenhuma taxa move
    mais a taxa vezes as vendas que ela alcança. A reta passa pela taxa simulada e, na taxa zero,
    pela `parte_fixa`. Uma parte fixa menor que a verdadeira, como a que deixa de fora um bônus em
    reais dentro do escopo, inclina a reta e põe a taxa acima da que cabe, nunca abaixo, salvo o
    truncamento: a simulação da candidata confirma, e o refinamento corrige a seguinte. Com a parte
    fixa no orçamento ou acima dele, nenhuma redução de taxa cabe.
    """
    if percentual <= 0 or parte_fixa < 0 or not parte_fixa < orcamento < simulado:
        return None

    candidato = (percentual * (orcamento - parte_fixa) / (simulado - parte_fixa)).quantize(
        QUANTUM, rounding=ROUND_DOWN
    )
    if candidato <= 0 or candidato >= percentual:
        return None
    return candidato


def comissao_fora_da_regra(
    representacao: Mapping[str, ValorRegra], linhas: Mapping[str, object] | None
) -> Decimal | None:
    """A comissão simulada das linhas que a regra não alcança, ou None sem o detalhamento.

    Só conta a linha sem contribuição de elemento algum: uma que mudou depende da regra, e tomá-la
    por fixa poria a estimativa abaixo da taxa que cabe. A linha que a regra alcança fica de fora
    mesmo sem contribuição, porque a taxa atual dela pode ser a mesma da regra.
    """
    if linhas is None:
        return None
    alcance = AlcanceDaRegra.da(representacao)
    fixa = Decimal(0)
    for competencia, da_competencia in linhas.items():
        if not isinstance(da_competencia, Mapping):
            return None
        for linha in da_competencia.values():
            if not isinstance(linha, Mapping):
                return None
            comissao = _numero(linha.get("comissao_simulada"))
            if comissao is None:
                return None
            if not linha.get("contribuicoes") and not alcance.alcanca(competencia, linha):
                fixa += comissao
    return fixa


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
    parte_fixa: Decimal | None,
    anteriores: Sequence[TaxaSimulada] = (),
) -> Alternativa:
    """Monta a regra alternativa reduzindo todas as taxas na mesma proporção.

    `anteriores` são as taxas de referência já simuladas da regra e das versões que ela adapta.
    Com duas ou mais distintas, a referência é refinada por elas; com menos, ainda não há reta, e
    ela sai da simulação que não coube e da `parte_fixa`, a comissão das linhas que a regra não
    alcança (`comissao_fora_da_regra`). Sem ela, a parte fixa é zero, e a primeira taxa é a
    sondagem, proporcional ao orçamento. A representação proposta passa pela mesma verificação
    de coerência que barra uma regra na entrada: propor algo que já nasce inválido custaria um
    ciclo inteiro de simulação para terminar no mesmo lugar.
    """
    referencia = taxa_de_referencia(representacao)
    if referencia is None:
        return Alternativa(MOTIVO_NAO_SUPORTADA)

    if len({taxa.percentual for taxa in anteriores}) >= 2:
        metodo = METODO_REFINAMENTO
        candidato = percentual_refinado(anteriores, orcamento)
    else:
        # Com a parte fixa acima do orçamento, nenhuma taxa cabe. A primeira alternativa ainda é
        # simulada, pela sondagem, para o usuário ver a regra reduzida e o motivo de ela não
        # caber; a reta do refinamento cruza o orçamento abaixo de zero e encerra a iteração na
        # tentativa seguinte.
        estimada = parte_fixa is not None and parte_fixa < orcamento
        metodo = METODO_ESTIMATIVA if estimada else METODO_SONDAGEM
        candidato = percentual_que_cabe(
            referencia,
            simulado,
            orcamento,
            parte_fixa=parte_fixa if parte_fixa is not None and estimada else Decimal(0),
        )
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
