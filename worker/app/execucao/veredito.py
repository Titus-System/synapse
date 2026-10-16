"""Julgamento do resultado contra o baseline, a cobertura e o orçamento, fora do container
(T-066, T-241, T-270, T-281).

O container produz números crus. O processo do worker, que o código gerado não alcança:

1. confere o ``totais.baseline`` devolvido contra o baseline que o worker mantém, e que os
   totais fecham entre si: o congelado numa execução sobre as vendas históricas, e o que o
   próprio worker reapurou sobre as vendas escaladas numa execução na meta de venda;
2. com isso, a diferença absoluta e a percentual do container passam a ser as do baseline do
   worker, e seguem como vieram, sem recomposição;
3. quando o comando trouxe ``elementos_exigidos``, confere a cobertura: todo elemento exigido
   está declarado pelo código, e toda contribuição da decomposição é de um elemento exigido;
4. aplica o orçamento e emite o veredito, quando o comando trouxe orçamento.

Sem orçamento, as conferências 1 a 3 são as mesmas, e só a 4 não acontece: o resultado conferido
segue sem ``totais.orcamento`` e sem veredito, porque não há critério que o julgue (T-281).

Todo sucesso conferido leva ``totais.vendas_historicas``, o total de vendas das competências
lido das bases do worker, e nunca do container (T-270). Na meta, o veredito compara o simulado
na meta com o orçamento.

O orçamento é o único parâmetro que **julga** o resultado, e nunca entrou no container: código
gerado que o enxergasse poderia mirar nele (ARCHITECTURE.md §3.4).

``indeterminado`` é o veredito de todo desfecho que não é ``sucesso``: sem número confiável não
há julgamento. Um ``sucesso`` sai ``viavel`` ou ``inviavel`` quando há orçamento, e sem veredito
(``None``) quando não há, nunca ``indeterminado``, porque a api lê ``sucesso`` +
``indeterminado`` como número confiável ainda sem julgamento. Na gravação e no
evento (T-067), o veredito de um desfecho que não é ``sucesso`` vai nulo, como mandam
``simulacao-concluida.schema.json`` e ``resultados_simulacao.veredito``.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, NotRequired, TypedDict

from app.execucao.baseline import BaselinesCongelados, CompetenciaSemBaselineError
from app.execucao.bases import BasesDoWorker
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
    """``resultado-totais.schema.json``: os totais do container mais o que só o worker
    acrescenta, o total de vendas das competências e o orçamento aplicado, que falta quando o
    comando não trouxe orçamento."""

    baseline: float
    simulado: float
    diferenca_abs: float
    diferenca_pct: float
    vendas_historicas: float
    orcamento: NotRequired[float]


class ResultadoJulgado(TypedDict):
    """``resultado-simulacao.schema.json`` inteiro, pronto para ``resultados_simulacao``."""

    totais: TotaisJulgados
    assercoes: list[Desfecho]
    decomposicao: Decomposicao


@dataclass(frozen=True)
class CoberturaIncompleta:
    """O que reprovou a conferência de cobertura. Ao menos uma das duas listas tem item."""

    # Exigidos pelo comando e não declarados pelo código, na ordem do comando. Vêm do codegen.
    ausentes: tuple[str, ...]
    # Com contribuição e não exigidos, na ordem da decomposição. Vêm do código gerado, já
    # validados no espaço de elemento_ref pelo schema do resultado.
    fora_da_regra: tuple[str, ...]


@dataclass(frozen=True)
class Julgamento:
    """O desfecho da T-065 julgado. ``classe`` e ``motivo`` só mudam quando o baseline diverge
    ou a cobertura está incompleta.

    ``resultado`` e ``desfecho`` carregam conteúdo do container e ficam fora do ``repr``."""

    classe: Classe
    motivo: Motivo
    # None só num sucesso sem orçamento: o número vale, mas não há critério que o julgue.
    veredito: Veredito | None
    # Só em sucesso: o resultado do container, com ``totais.orcamento`` acrescentado quando há
    # orçamento.
    resultado: ResultadoJulgado | None = field(default=None, repr=False)
    desfecho: DesfechoClassificado | None = field(default=None, repr=False)
    # Só quando o motivo é cobertura_incompleta.
    cobertura: CoberturaIncompleta | None = None

    @property
    def totais(self) -> TotaisJulgados | None:
        return self.resultado["totais"] if self.resultado is not None else None


def desfecho_da_execucao(julgamento: Julgamento) -> str:
    """O desfecho da execução julgada como rótulo de métrica, de conjunto fechado
    (``DESFECHOS_DA_EXECUCAO``): o veredito de um sucesso, ``sem_orcamento`` num sucesso sem
    veredito, e a classe nos demais."""
    if julgamento.classe != "sucesso":
        return julgamento.classe
    return julgamento.veredito or "sem_orcamento"


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


def conferir_cobertura(
    exigidos: Sequence[str],
    implementados: Sequence[str] | None,
    com_contribuicao: Iterable[str],
) -> CoberturaIncompleta | None:
    """None quando a cobertura está completa (``contracts/harness/README.md``, seção
    "Conferência de cobertura").

    São duas condições: todo elemento exigido está declarado, e todo elemento com contribuição é
    exigido. Juntas, garantem que todo elemento com contribuição está declarado. Um elemento
    declarado sem contribuição é aceito, porque exclusão, condição de limiar e elemento sem
    ocorrência no período não geram valor próprio; declarar a mais também é. Sem declaração
    (``implementados`` None), nenhum elemento exigido está declarado.
    """
    declarados = set(implementados or ())
    ausentes = tuple(elemento for elemento in exigidos if elemento not in declarados)
    da_regra = set(exigidos)
    fora_da_regra = tuple(elemento for elemento in com_contribuicao if elemento not in da_regra)
    if not ausentes and not fora_da_regra:
        return None
    return CoberturaIncompleta(ausentes=ausentes, fora_da_regra=fora_da_regra)


def julgar(
    desfecho: DesfechoClassificado,
    competencias: list[str],
    orcamento: float | None,
    baselines: BaselinesCongelados,
    *,
    elementos_exigidos: Sequence[str] | None,
    bases: BasesDoWorker,
    baseline_na_meta: Decimal | None = None,
) -> Julgamento:
    """``elementos_exigidos`` é o do comando, e None quando ele não o trouxe: aí a cobertura não
    é conferida, e um comando publicado antes da T-241 segue julgado como antes.

    ``orcamento`` None é o job sem orçamento: o sucesso sai sem veredito e sem
    ``totais.orcamento``, depois das mesmas conferências.

    ``baseline_na_meta`` é o total que o worker reapurou sobre as vendas escaladas, numa
    execução na meta de venda, e é contra ele que o baseline do container é conferido. None é a
    execução sobre as vendas históricas, conferida contra o congelado como sempre foi."""
    if desfecho.classe != "sucesso" or desfecho.resultado is None:
        return Julgamento(desfecho.classe, desfecho.motivo, "indeterminado", desfecho=desfecho)

    totais = desfecho.resultado["totais"]
    if baseline_na_meta is not None:
        esperado = baseline_na_meta
    else:
        try:
            esperado = baselines.total(competencias)
        # O harness não produz sucesso para uma competência sem baseline na imagem: se produziu,
        # a imagem tem um baseline que o worker não tem, e o número não tem com o que ser
        # conferido.
        except CompetenciaSemBaselineError:
            return Julgamento(
                "erro_codigo", "baseline_divergente", "indeterminado", desfecho=desfecho
            )
    if not _totais_conferem(totais, esperado):
        return Julgamento("erro_codigo", "baseline_divergente", "indeterminado", desfecho=desfecho)
    if elementos_exigidos is not None:
        # As chaves de decomposicao.elemento são os elemento_ref de contribuicoes: o harness
        # cria uma para cada elemento a que o código atribuiu contribuição, mesmo que somem zero.
        cobertura = conferir_cobertura(
            elementos_exigidos,
            desfecho.elementos_implementados,
            desfecho.resultado["decomposicao"]["elemento"],
        )
        if cobertura is not None:
            return Julgamento(
                "erro_codigo",
                "cobertura_incompleta",
                "indeterminado",
                desfecho=desfecho,
                cobertura=cobertura,
            )

    totais_julgados = TotaisJulgados(
        baseline=totais["baseline"],
        simulado=totais["simulado"],
        diferenca_abs=totais["diferenca_abs"],
        diferenca_pct=totais["diferenca_pct"],
        # Conferido o baseline, as competências são as das bases do worker.
        vendas_historicas=float(bases.vendas_historicas(competencias)),
    )
    veredito: Veredito | None = None
    if orcamento is not None:
        totais_julgados["orcamento"] = orcamento
        veredito = decidir_veredito(totais["simulado"], orcamento)
    resultado = ResultadoJulgado(
        totais=totais_julgados,
        assercoes=desfecho.resultado["assercoes"],
        decomposicao=desfecho.resultado["decomposicao"],
    )
    return Julgamento("sucesso", "ok", veredito, resultado=resultado, desfecho=desfecho)


def _totais_conferem(totais: Totais, baseline_do_worker: Decimal) -> bool:
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
        baseline == baseline_do_worker
        and Decimal(str(totais["diferenca_abs"])) == diferenca
        and totais["diferenca_pct"] == pct
    )
