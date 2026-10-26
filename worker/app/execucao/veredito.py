"""Julgamento do resultado contra o baseline, a cobertura e o orçamento, fora do container
(T-066, T-241, T-262, T-270, T-281, T-282).

O container produz números crus. O processo do worker, que o código gerado não alcança:

1. confere o ``totais.baseline`` devolvido contra o baseline que o worker mantém, e que os
   totais fecham entre si: o congelado numa execução sobre as vendas históricas, e o que o
   próprio worker reapurou sobre as vendas escaladas numa execução na meta de venda;
2. confere o detalhamento contra o mesmo baseline, linha a linha, e a coerência entre o
   detalhamento, os totais e as quebras da decomposição (``app/execucao/conferencia.py``);
3. com isso, a diferença absoluta e a percentual do container passam a ser as do baseline do
   worker, e seguem como vieram, sem recomposição;
4. quando o comando trouxe ``elementos_exigidos``, confere a cobertura: todo elemento exigido
   está declarado pelo código, e toda contribuição da decomposição é de um elemento exigido;
5. quando o comando trouxe ``alcance``, confere o escopo: toda linha fora do alcance da regra
   conserva a comissão do baseline (``app/execucao/escopo.py``);
6. aplica o orçamento e emite o veredito, quando o comando trouxe orçamento.

Sem orçamento, as conferências 1 a 5 são as mesmas, e só a 6 não acontece: o resultado conferido
segue sem ``totais.orcamento`` e sem veredito, porque não há critério que o julgue (T-281).

Todo sucesso conferido leva ``totais.vendas_historicas``, o total de vendas das competências
lido das bases do worker, e nunca do container (T-270). Na meta, o veredito compara o simulado
na meta com o orçamento. Das mesmas bases, cada linha do detalhamento recebe ``vendas``, o total
vendido da matrícula na competência: as vendas históricas, ou as escaladas até a meta, que são
as que a execução usou para apurar as comissões da linha (T-282).

O orçamento é o único parâmetro que **julga** o resultado, e nunca entrou no container: código
gerado que o enxergasse poderia mirar nele (ARCHITECTURE.md §3.4).

``indeterminado`` é o veredito de todo desfecho que não é ``sucesso``: sem número confiável não
há julgamento. Um ``sucesso`` sai ``viavel`` ou ``inviavel`` quando há orçamento, e sem veredito
(``None``) quando não há, nunca ``indeterminado``, porque a api lê ``sucesso`` +
``indeterminado`` como número confiável ainda sem julgamento. Na gravação e no
evento (T-067), o veredito de um desfecho que não é ``sucesso`` vai nulo, como mandam
``simulacao-concluida.schema.json`` e ``resultados_simulacao.veredito``.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, NotRequired, TypedDict

from app.execucao.baseline import (
    BaselinesCongelados,
    CompetenciaSemBaselineError,
    LinhasDoBaseline,
    total_das_linhas,
)
from app.execucao.bases import BasesDoWorker
from app.execucao.coleta import (
    Classe,
    DesfechoClassificado,
    Motivo,
    classificar_falha_de_infra,
)
from app.execucao.conferencia import (
    Divergencia,
    MotivoDaRecusa,
    Verificacao,
    conferir_detalhamento,
)
from app.execucao.escopo import ForaDoEscopo, conferir_escopo
from app.mensageria.contracts import AlcanceDaRegra
from app.sandbox.assercoes import Desfecho
from app.sandbox.regras_base import CENTAVO
from app.sandbox.resultado import Decomposicao, LinhaDetalhada, LinhasResultado, Totais

type Veredito = Literal["viavel", "inviavel", "indeterminado"]
# O que a conferência do resultado decidiu (T-066, T-262): aceito, ou recusado por um dos dois
# motivos. Rótulo de conjunto fechado da métrica de conferências.
type ResultadoDaConferencia = Literal["coerente", MotivoDaRecusa]


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


class LinhaJulgada(LinhaDetalhada):
    """``resultado-linhas.schema.json``: a linha do container mais o que só o worker acrescenta,
    o total vendido da matrícula na competência."""

    vendas: float


type LinhasJulgadas = dict[str, dict[str, LinhaJulgada]]


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
    # Só em sucesso: o detalhamento do container com ``vendas`` acrescentado a cada linha.
    linhas: LinhasJulgadas | None = field(default=None, repr=False)
    # Só quando o motivo é cobertura_incompleta.
    cobertura: CoberturaIncompleta | None = None
    # Só quando o motivo é fora_do_escopo.
    fora_do_escopo: ForaDoEscopo | None = None
    # Só quando o desfecho era sucesso e o resultado passou pela conferência: o que ela decidiu,
    # e a verificação que falhou quando recusou.
    conferencia: ResultadoDaConferencia | None = None
    verificacao: Verificacao | None = None

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
    baseline_na_meta: LinhasDoBaseline | None = None,
    meta_venda: float | None = None,
    alcance: AlcanceDaRegra | None = None,
) -> Julgamento:
    """``elementos_exigidos`` é o do comando, e None quando ele não o trouxe: aí a cobertura não
    é conferida, e um comando publicado antes da T-241 segue julgado como antes. ``alcance``
    também é o do comando, e sem ele o escopo não é conferido.

    ``orcamento`` None é o job sem orçamento: o sucesso sai sem veredito e sem
    ``totais.orcamento``, depois das mesmas conferências.

    ``baseline_na_meta`` é o baseline que o worker reapurou sobre as vendas escaladas, linha a
    linha, numa execução na meta de venda, e é contra ele que o baseline do container e o
    detalhamento são conferidos. None é a execução sobre as vendas históricas, conferida contra o
    congelado.

    ``meta_venda`` é a do comando, e vem junto com ``baseline_na_meta``: com ela, o total vendido
    de cada linha é o das vendas escaladas até a meta."""
    if (baseline_na_meta is None) != (meta_venda is None):
        raise ValueError("baseline_na_meta e meta_venda vêm juntos, ou nenhum dos dois")
    if desfecho.classe != "sucesso" or desfecho.resultado is None:
        return Julgamento(desfecho.classe, desfecho.motivo, "indeterminado", desfecho=desfecho)

    totais = desfecho.resultado["totais"]
    if baseline_na_meta is not None:
        baseline = baseline_na_meta
        esperado = total_das_linhas(baseline_na_meta)
    else:
        try:
            baseline = baselines.linhas_do_periodo(competencias)
            esperado = baselines.total(competencias)
        # O harness não produz sucesso para uma competência sem baseline na imagem: se produziu,
        # a imagem tem um baseline que o worker não tem, e o número não tem com o que ser
        # conferido.
        except CompetenciaSemBaselineError:
            return _recusado(desfecho, Divergencia("baseline_divergente", "baseline"))
    if not _totais_conferem(totais, esperado):
        return _recusado(desfecho, Divergencia("baseline_divergente", "baseline"))
    # A coleta recusa o sucesso sem detalhamento (T-259); sem ele, nada confere com o baseline.
    detalhamento = desfecho.linhas if desfecho.linhas is not None else {}
    divergencia = conferir_detalhamento(desfecho.resultado, detalhamento, baseline)
    if divergencia is not None:
        return _recusado(desfecho, divergencia)
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
                conferencia="coerente",
            )
    if alcance is not None:
        fora_do_escopo = conferir_escopo(alcance, detalhamento)
        if fora_do_escopo is not None:
            return Julgamento(
                "erro_codigo",
                "fora_do_escopo",
                "indeterminado",
                desfecho=desfecho,
                fora_do_escopo=fora_do_escopo,
                conferencia="coerente",
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
    linhas = None
    if desfecho.linhas is not None:
        linhas = _com_vendas(desfecho.linhas, bases.vendas_por_linha(competencias, meta_venda))
    return Julgamento(
        "sucesso",
        "ok",
        veredito,
        resultado=resultado,
        desfecho=desfecho,
        linhas=linhas,
        conferencia="coerente",
    )


def _recusado(desfecho: DesfechoClassificado, divergencia: Divergencia) -> Julgamento:
    """O resultado não se sustenta: ``erro_codigo``, sem veredito e sem linhas a gravar."""
    return Julgamento(
        "erro_codigo",
        divergencia.motivo,
        "indeterminado",
        desfecho=desfecho,
        conferencia=divergencia.motivo,
        verificacao=divergencia.verificacao,
    )


def _com_vendas(
    linhas: LinhasResultado, vendas: Mapping[tuple[str, str], Decimal]
) -> LinhasJulgadas:
    """Cada linha como veio do container, com o total vendido que o worker somou, arredondado a
    centavos como as comissões da linha. A matrícula que não vendeu no mês fica com zero, e não
    sem o campo, que é o que distingue as linhas gravadas antes dele."""
    julgadas: LinhasJulgadas = {}
    for competencia, colaboradores in linhas.items():
        julgadas[competencia] = {}
        for matricula, linha in colaboradores.items():
            total = vendas.get((competencia, matricula), Decimal(0))
            julgadas[competencia][matricula] = LinhaJulgada(
                **linha, vendas=float(total.quantize(CENTAVO, rounding=ROUND_HALF_UP))
            )
    return julgadas


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
