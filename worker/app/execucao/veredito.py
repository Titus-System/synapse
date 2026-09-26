"""Julgamento do resultado contra o baseline e o orçamento, fora do container (T-066).

O container produz números crus. O processo do worker, que o código gerado não alcança:

1. confere o ``totais.baseline`` devolvido contra o baseline congelado que o worker mantém, e
   que os totais fecham entre si;
2. com isso, a diferença absoluta e a percentual do container passam a ser as do baseline do
   worker, e seguem como vieram, sem recomposição;
3. aplica o orçamento e emite o veredito.

O orçamento é o único parâmetro que **julga** o resultado, e nunca entrou no container: código
gerado que o enxergasse poderia mirar nele (ARCHITECTURE.md §3.4).

``indeterminado`` é o veredito de todo desfecho que não é ``sucesso``: sem número confiável não
há julgamento. Um ``sucesso`` sai sempre ``viavel`` ou ``inviavel``, porque a api lê
``sucesso`` + ``indeterminado`` como número confiável ainda sem julgamento. Na gravação e no
evento (T-067), o veredito de um desfecho que não é ``sucesso`` vai nulo, como mandam
``simulacao-concluida.schema.json`` e ``resultados_simulacao.veredito``.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, TypedDict

from app.execucao.baseline import BaselinesCongelados, CompetenciaSemBaselineError
from app.execucao.coleta import (
    Classe,
    DesfechoClassificado,
    Motivo,
    classificar_falha_de_infra,
)
from app.sandbox.assercoes import Desfecho
from app.sandbox.resultado import Decomposicao, Totais

type Veredito = Literal["viavel", "inviavel", "indeterminado"]


class TotaisJulgados(TypedDict):
    """``resultado-totais.schema.json``: os totais do container mais o orçamento aplicado."""

    baseline: float
    simulado: float
    diferenca_abs: float
    diferenca_pct: float
    orcamento: float


class ResultadoJulgado(TypedDict):
    """``resultado-simulacao.schema.json`` inteiro, pronto para ``resultados_simulacao``."""

    totais: TotaisJulgados
    assercoes: list[Desfecho]
    decomposicao: Decomposicao


@dataclass(frozen=True)
class Julgamento:
    """O desfecho da T-065 julgado. ``classe`` e ``motivo`` só mudam quando o baseline diverge.

    ``resultado`` e ``desfecho`` carregam conteúdo do container e ficam fora do ``repr``."""

    classe: Classe
    motivo: Motivo
    veredito: Veredito
    # Só em sucesso: o resultado do container com ``totais.orcamento`` acrescentado.
    resultado: ResultadoJulgado | None = field(default=None, repr=False)
    desfecho: DesfechoClassificado | None = field(default=None, repr=False)

    @property
    def totais(self) -> TotaisJulgados | None:
        return self.resultado["totais"] if self.resultado is not None else None


def julgamento_de_infra() -> Julgamento:
    """O container não pôde ser criado, iniciado ou lido: nada rodou, e não há o que julgar."""
    return Julgamento("erro_infra", "infra", "indeterminado", desfecho=classificar_falha_de_infra())


def decidir_veredito(simulado: float, orcamento: float) -> Veredito:
    """Viável quando o total simulado do período **cabe** no orçamento, igualdade incluída
    (DEC-093). O total absoluto, não a diferença: é ele que o orçamento confronta.

    A comparação é em ``Decimal`` a partir da representação de cada número, sem arredondar o
    orçamento: um orçamento com fração de centavo julga como veio.
    """
    return "viavel" if Decimal(str(simulado)) <= Decimal(str(orcamento)) else "inviavel"


def julgar(
    desfecho: DesfechoClassificado,
    competencias: list[str],
    orcamento: float,
    baselines: BaselinesCongelados,
) -> Julgamento:
    if desfecho.classe != "sucesso" or desfecho.resultado is None:
        return Julgamento(desfecho.classe, desfecho.motivo, "indeterminado", desfecho=desfecho)

    totais = desfecho.resultado["totais"]
    try:
        congelado = baselines.total(competencias)
    # O harness não produz sucesso para uma competência sem baseline na imagem: se produziu, a
    # imagem tem um baseline que o worker não tem, e o número não tem com o que ser conferido.
    except CompetenciaSemBaselineError:
        return Julgamento("erro_codigo", "baseline_divergente", "indeterminado", desfecho=desfecho)
    if not _totais_conferem(totais, congelado):
        return Julgamento("erro_codigo", "baseline_divergente", "indeterminado", desfecho=desfecho)

    resultado = ResultadoJulgado(
        totais=TotaisJulgados(
            baseline=totais["baseline"],
            simulado=totais["simulado"],
            diferenca_abs=totais["diferenca_abs"],
            diferenca_pct=totais["diferenca_pct"],
            orcamento=orcamento,
        ),
        assercoes=desfecho.resultado["assercoes"],
        decomposicao=desfecho.resultado["decomposicao"],
    )
    veredito = decidir_veredito(totais["simulado"], orcamento)
    return Julgamento("sucesso", "ok", veredito, resultado=resultado, desfecho=desfecho)


def _totais_conferem(totais: Totais, baseline_congelado: Decimal) -> bool:
    """O baseline do container é o do worker, e a diferença é a que os dois totais implicam.

    As mesmas contas da T-035 (``resultado.montar_resultado``) sobre os mesmos centavos: a
    igualdade é exata, e qualquer divergência é adulteração ou descompasso, nunca arredondamento.
    """
    baseline = Decimal(str(totais["baseline"]))
    simulado = Decimal(str(totais["simulado"]))
    diferenca = simulado - baseline
    # Baseline zero não tem fração definida; a T-035 publica 0.0.
    pct = float(diferenca / baseline) if baseline else 0.0
    return (
        baseline == baseline_congelado
        and Decimal(str(totais["diferenca_abs"])) == diferenca
        and totais["diferenca_pct"] == pct
    )
