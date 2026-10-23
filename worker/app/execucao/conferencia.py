"""Conferência do detalhamento e das quebras do resultado, fora do container (T-262).

A regra roda no mesmo processo do harness e pode forjar qualquer byte do stdout. Com o
detalhamento por competência e matrícula (T-259), o worker tem como conferir o resultado inteiro,
e não só o total do baseline (T-066). Ele não recalcula a regra: soma o que o container devolveu e
compara com o que o próprio container declarou e com o baseline que o worker mantém.

As verificações, nesta ordem, param na primeira que falha:

1. ``baseline``: o detalhamento traz exatamente as competências e matrículas do baseline do
   worker, e em cada linha a loja, a marca, o cargo e a comissão do baseline são os dele;
2. ``soma_do_detalhamento``: a soma de ``comissao_simulada`` é ``totais.simulado``;
3. ``diferencas``: em cada linha, ``diferenca`` é a comissão simulada menos a do baseline;
4. ``contribuicoes``: em cada linha, as contribuições somam a ``diferenca``;
5. ``quebras``: cada quebra da decomposição é a soma do detalhamento pela sua dimensão.

A primeira é ``baseline_divergente``, o motivo que a T-066 já usa para o total; as demais são
``resultado_incoerente``. A igualdade é exata, em centavos: as parcelas já chegam arredondadas
por linha (T-035), e uma divergência é adulteração ou defeito, nunca arredondamento.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, cast

from app.execucao.baseline import LinhasDoBaseline
from app.sandbox.resultado import LinhaDetalhada, LinhasResultado, ResultadoSimulacao

type Verificacao = Literal[
    "baseline", "soma_do_detalhamento", "diferencas", "contribuicoes", "quebras"
]
type MotivoDaRecusa = Literal["baseline_divergente", "resultado_incoerente"]

VERIFICACOES: tuple[Verificacao, ...] = (
    "baseline",
    "soma_do_detalhamento",
    "diferencas",
    "contribuicoes",
    "quebras",
)

type _Linha = tuple[str, str, LinhaDetalhada]


@dataclass(frozen=True)
class Divergencia:
    """Por que o resultado foi recusado: o motivo e a verificação que falhou, sem conteúdo do
    detalhamento."""

    motivo: MotivoDaRecusa
    verificacao: Verificacao


def conferir_detalhamento(
    resultado: ResultadoSimulacao, linhas: LinhasResultado, baseline: LinhasDoBaseline
) -> Divergencia | None:
    """None quando o detalhamento fecha com o baseline e com os totais e as quebras.

    ``baseline`` é o do worker para as competências do job: o congelado, ou o reapurado sobre as
    vendas escaladas numa execução na meta (T-270)."""
    if not _baseline_confere(linhas, baseline):
        return Divergencia("baseline_divergente", "baseline")
    todas = [
        (competencia, matricula, linha)
        for competencia, da_competencia in linhas.items()
        for matricula, linha in da_competencia.items()
    ]
    if _somar(linha["comissao_simulada"] for _, _, linha in todas) != _dec(
        resultado["totais"]["simulado"]
    ):
        return Divergencia("resultado_incoerente", "soma_do_detalhamento")
    if any(
        _dec(linha["diferenca"])
        != _dec(linha["comissao_simulada"]) - _dec(linha["comissao_baseline"])
        for _, _, linha in todas
    ):
        return Divergencia("resultado_incoerente", "diferencas")
    if any(
        _somar(linha["contribuicoes"].values()) != _dec(linha["diferenca"]) for _, _, linha in todas
    ):
        return Divergencia("resultado_incoerente", "contribuicoes")
    if not _quebras_conferem(resultado, todas, list(linhas)):
        return Divergencia("resultado_incoerente", "quebras")
    return None


def _baseline_confere(linhas: LinhasResultado, baseline: LinhasDoBaseline) -> bool:
    if linhas.keys() != baseline.keys():
        return False
    for competencia, do_baseline in baseline.items():
        detalhadas = linhas[competencia]
        if detalhadas.keys() != do_baseline.keys():
            return False
        for matricula, esperada in do_baseline.items():
            linha = detalhadas[matricula]
            if (
                linha["cod_loja"] != esperada.cod_loja
                or linha["cod_marca"] != esperada.cod_marca
                or linha["cod_cargo"] != esperada.cod_cargo
                or _dec(linha["comissao_baseline"]) != esperada.comissao
            ):
                return False
    return True


def _quebras_conferem(
    resultado: ResultadoSimulacao, todas: list[_Linha], competencias: list[str]
) -> bool:
    """Cada quebra é a soma do detalhamento, com as mesmas chaves que o harness cria (T-035).

    As quebras por loja, marca, cargo e matrícula têm uma chave para cada código das linhas,
    mesmo com soma zero, e as por competência têm uma chave para cada competência do período.
    Por elemento, o harness guarda um elemento cujas parcelas somam zero (T-241), mas o
    detalhamento omite a parcela zero da linha: um elemento só na decomposição vale se for zero.

    As três quebras absolutas são opcionais no contrato só pelos resultados gravados antes delas;
    o harness sempre as produz, e um sucesso sem elas não é o que ele devolveria.
    """
    decomposicao = cast(Mapping[str, Mapping[str, float]], resultado["decomposicao"])
    esperadas: dict[str, dict[str, Decimal]] = {
        "loja": _agrupar(todas, _loja, _diferenca),
        "marca": _agrupar(todas, _marca, _diferenca),
        "cargo": _agrupar(todas, _cargo, _diferenca),
        "competencia": _agrupar(todas, _competencia, _diferenca, competencias),
        "matricula": _agrupar(todas, _matricula, _simulada),
        "loja_absoluto": _agrupar(todas, _loja, _simulada),
        "competencia_absoluto": _agrupar(todas, _competencia, _simulada, competencias),
    }
    for nome, esperada in esperadas.items():
        quebra = decomposicao.get(nome)
        if quebra is None or quebra.keys() != esperada.keys():
            return False
        if any(_dec(valor) != esperada[chave] for chave, valor in quebra.items()):
            return False

    por_elemento: dict[str, Decimal] = {}
    for _, _, linha in todas:
        for elemento, parcela in linha["contribuicoes"].items():
            por_elemento[elemento] = por_elemento.get(elemento, Decimal(0)) + _dec(parcela)
    quebra_por_elemento = decomposicao["elemento"]
    if not por_elemento.keys() <= quebra_por_elemento.keys():
        return False
    return all(
        _dec(valor) == por_elemento.get(chave, Decimal(0))
        for chave, valor in quebra_por_elemento.items()
    )


def _agrupar(
    todas: list[_Linha],
    chave: Callable[[_Linha], str],
    valor: Callable[[_Linha], float],
    chaves_fixas: Iterable[str] = (),
) -> dict[str, Decimal]:
    grupos = dict.fromkeys(chaves_fixas, Decimal(0))
    for item in todas:
        grupo = chave(item)
        grupos[grupo] = grupos.get(grupo, Decimal(0)) + _dec(valor(item))
    return grupos


def _competencia(item: _Linha) -> str:
    return item[0]


def _matricula(item: _Linha) -> str:
    return item[1]


def _loja(item: _Linha) -> str:
    return item[2]["cod_loja"]


def _marca(item: _Linha) -> str:
    return item[2]["cod_marca"]


def _cargo(item: _Linha) -> str:
    return item[2]["cod_cargo"]


def _diferenca(item: _Linha) -> float:
    return item[2]["diferenca"]


def _simulada(item: _Linha) -> float:
    return item[2]["comissao_simulada"]


def _somar(valores: Iterable[float]) -> Decimal:
    return sum((_dec(valor) for valor in valores), Decimal(0))


def _dec(valor: float) -> Decimal:
    """O número como o JSON o trouxe: ``Decimal(str(float))`` devolve os centavos que o harness
    serializou (``resultado._moeda``), sem o erro binário do float."""
    return Decimal(str(valor))
