"""Agregação do resultado da simulação dentro do sandbox (T-035).

Converte o retorno da função gerada - apuração por matrícula e contribuições por
elemento, na forma fixada pelo contrato da T-034 - na saída decomposta de
``contracts/domain/resultado-simulacao.schema.json``. Sem I/O, sem rede e sem
pandas: só a biblioteca padrão e os helpers do próprio sandbox.

As cinco quebras da diferença somam ``totais.diferenca_abs``. As três quebras
absolutas e o detalhamento somam ``totais.simulado``. O orçamento e o veredito não
aparecem aqui - quem os aplica é o worker, fora do container (T-066), porque
quem produz o número não deve alcançar o critério que vai julgá-lo.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple, SupportsIndex, TypedDict, cast

from app.sandbox.assercoes import Desfecho, numero_finito
from app.sandbox.regras_base import (
    CENTAVO,
    DataFrameLike,
    Registro,
    RegraBaseError,
    _extrair_linhas,
    _moeda,
    _texto,
)

# Cópias dos padrões de comum.schema.json. contracts/ é insumo de build, nunca
# dependência de runtime (ADR-002), por isso os schemas não são lidos aqui; um
# teste confere que estas constantes não divergiram do contrato.
PADRAO_ELEMENTO_REF = re.compile(r"^(nucleo\.[a-z_]+|elem\.[0-9]+)$")
PADRAO_COMPETENCIA = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

MAXIMO_CHAVES_NA_MENSAGEM = 5

type Tabela = Sequence[Registro] | DataFrameLike
type Chave = tuple[str, str]


class Totais(TypedDict):
    """Agregados do período inteiro, somando todas as competências do job.

    ``orcamento`` não entra: o container não o recebe, e é o worker que o
    acrescenta junto do veredito (T-066).
    """

    baseline: float
    simulado: float
    diferenca_abs: float
    diferenca_pct: float


class Decomposicao(TypedDict):
    """Cinco quebras da diferença e três do total simulado (T-200 C)."""

    elemento: dict[str, float]
    loja: dict[str, float]
    marca: dict[str, float]
    cargo: dict[str, float]
    competencia: dict[str, float]
    matricula: dict[str, float]
    loja_absoluto: dict[str, float]
    competencia_absoluto: dict[str, float]


class ResultadoSimulacao(TypedDict):
    totais: Totais
    assercoes: list[Desfecho]
    decomposicao: Decomposicao


class LinhaDetalhada(TypedDict):
    cod_loja: str
    cod_marca: str
    cod_cargo: str
    comissao_baseline: float
    comissao_simulada: float
    diferenca: float
    contribuicoes: dict[str, float]


type LinhasResultado = dict[str, dict[str, LinhaDetalhada]]


@dataclass(frozen=True)
class ResultadoMontado:
    """Artefatos separados: a consulta do job não carrega o detalhamento (T-256)."""

    resultado: ResultadoSimulacao = field(repr=False)
    linhas: LinhasResultado = field(repr=False)


class ResultadoInvalidoError(ValueError):
    """Saída da função gerada fora do contrato da T-034."""


class DecomposicaoInconsistenteError(ResultadoInvalidoError):
    """As contribuições declaradas não explicam a diferença apurada."""


class _LinhaBase(NamedTuple):
    cod_loja: str
    cod_marca: str
    cod_cargo: str
    comissao: Decimal


def montar_resultado(
    saida: Mapping[str, Tabela],
    apuracao_base: Tabela,
    competencias: Sequence[str],
    *,
    assercoes: Sequence[Desfecho],
) -> ResultadoMontado:
    """Agrega o retorno da função gerada no formato de ``resultado-simulacao``.

    ``saida`` é o ``dict`` devolvido por ``aplicar_regra``, com
    ``apuracao_simulada`` e ``contribuicoes``. ``assercoes`` chega pronta da
    T-031: este módulo não verifica invariante nem emite veredito.
    """
    periodo = _conferir_competencias(competencias)
    base = _indexar_base(apuracao_base, periodo)
    delta_por_linha, simulado = _conferir_simulada(_tabela(saida, "apuracao_simulada"), base)
    contribuicoes = _agrupar_contribuicoes(_tabela(saida, "contribuicoes"), base)
    _conferir_atribuicao(delta_por_linha, contribuicoes)
    parcelas = _parcelas_por_linha(contribuicoes, delta_por_linha)

    baseline = _somar(linha.comissao for linha in base.values())
    diferenca = simulado - baseline

    resultado = ResultadoSimulacao(
        totais=Totais(
            baseline=_moeda(baseline),
            simulado=_moeda(simulado),
            diferenca_abs=_moeda(diferenca),
            # Fração, nunca porcentagem. Baseline zero não tem fração definida.
            diferenca_pct=float(diferenca / baseline) if baseline else 0.0,
        ),
        assercoes=list(assercoes),
        decomposicao=_decompor(base, delta_por_linha, parcelas, periodo),
    )
    return ResultadoMontado(resultado, _detalhar(base, delta_por_linha, parcelas, periodo))


def _conferir_competencias(competencias: Sequence[str]) -> tuple[str, ...]:
    """A ordem recebida é preservada: ela já chega crescente no comando de execução."""
    periodo = tuple(competencias)
    if not periodo:
        raise ResultadoInvalidoError("competencias não pode ser vazia")
    if len(set(periodo)) != len(periodo):
        raise ResultadoInvalidoError(f"competencias tem item repetido: {list(periodo)}")
    for competencia in periodo:
        if not PADRAO_COMPETENCIA.fullmatch(competencia):
            raise ResultadoInvalidoError(f"competência {competencia!r} não está em AAAA-MM")
    return periodo


def _indexar_base(apuracao_base: Tabela, periodo: tuple[str, ...]) -> dict[Chave, _LinhaBase]:
    """Indexa o baseline por matrícula e competência.

    A matrícula sozinha não é chave: num período de vários meses ela aparece uma
    vez por competência processada.
    """
    base: dict[Chave, _LinhaBase] = {}
    for registro in _linhas(apuracao_base, "apuracao_base"):
        chave = _chave(registro, "apuracao_base")
        if chave in base:
            raise ResultadoInvalidoError(f"apuracao_base repete {_descrever(chave)}")
        if chave[1] not in periodo:
            raise ResultadoInvalidoError(
                f"apuracao_base traz {_descrever(chave)}, fora do período {list(periodo)}"
            )
        base[chave] = _LinhaBase(
            cod_loja=_codigo_de(registro, "cod_loja", "apuracao_base"),
            cod_marca=_codigo_de(registro, "cod_marca", "apuracao_base"),
            cod_cargo=_codigo_de(registro, "cod_cargo", "apuracao_base"),
            comissao=_centavos(_valor_de(registro, "comissao", "apuracao_base")),
        )
    if not base:
        raise ResultadoInvalidoError("apuracao_base está vazia")
    return base


def _conferir_simulada(
    tabela: Tabela, base: Mapping[Chave, _LinhaBase]
) -> tuple[dict[Chave, Decimal], Decimal]:
    """Confere a apuração simulada contra o baseline e devolve o delta de cada linha.

    O contrato exige o mesmo conjunto de linhas do baseline: a regra ajusta a
    comissão onde se aplica, não cria nem remove matrícula ou competência.
    """
    delta: dict[Chave, Decimal] = {}
    simulado = Decimal(0)
    for registro in _linhas(tabela, "apuracao_simulada"):
        chave = _chave(registro, "apuracao_simulada")
        if chave in delta:
            raise ResultadoInvalidoError(f"apuracao_simulada repete {_descrever(chave)}")
        linha_base = base.get(chave)
        if linha_base is None:
            raise ResultadoInvalidoError(
                f"apuracao_simulada traz {_descrever(chave)}, que não existe no baseline"
            )
        _conferir_dimensoes(registro, linha_base, chave)
        # Arredondar uma vez por linha, como a T-032 faz ao congelar o baseline:
        # com as parcelas em centavos, toda quebra soma a diferença sem resíduo.
        comissao = _centavos(_valor_de(registro, "comissao", "apuracao_simulada"))
        delta[chave] = comissao - linha_base.comissao
        simulado += comissao
    ausentes = base.keys() - delta.keys()
    if ausentes:
        raise ResultadoInvalidoError(
            f"apuracao_simulada não trouxe {_listar(ausentes)}, que o baseline tem"
        )
    return delta, simulado


def _conferir_dimensoes(registro: Registro, linha_base: _LinhaBase, chave: Chave) -> None:
    """As dimensões da simulada precisam ser as do baseline.

    A agregação usa sempre as do baseline; conferir aqui existe para recusar o
    defeito em vez de absorvê-lo em silêncio.
    """
    for campo, esperado in (
        ("cod_loja", linha_base.cod_loja),
        ("cod_marca", linha_base.cod_marca),
        ("cod_cargo", linha_base.cod_cargo),
    ):
        encontrado = _codigo_de(registro, campo, "apuracao_simulada")
        if encontrado != esperado:
            raise ResultadoInvalidoError(
                f"apuracao_simulada mudou {campo} de {_descrever(chave)}: "
                f"baseline tem {esperado}, simulada tem {encontrado}"
            )


def _agrupar_contribuicoes(
    tabela: Tabela, base: Mapping[Chave, _LinhaBase]
) -> dict[Chave, dict[str, Decimal]]:
    """Soma as contribuições declaradas por linha e por elemento, sem arredondar.

    O arredondamento fica para o fim, quando cada balde de elemento já está
    fechado; arredondar cada contribuição aqui acumularia centavos à toa.
    """
    contribuicoes: dict[Chave, dict[str, Decimal]] = {}
    for registro in _linhas(tabela, "contribuicoes"):
        chave = _chave(registro, "contribuicoes")
        if chave not in base:
            raise ResultadoInvalidoError(
                f"contribuicoes traz {_descrever(chave)}, que não existe no baseline"
            )
        elemento = _texto_de(registro, "elemento_ref", "contribuicoes")
        if not PADRAO_ELEMENTO_REF.fullmatch(elemento):
            raise ResultadoInvalidoError(
                f"contribuicoes.elemento_ref {elemento!r} está fora do espaço de "
                "identificadores da representação (nucleo.<campo> ou elem.<n>)"
            )
        por_elemento = contribuicoes.setdefault(chave, {})
        delta = _valor_de(registro, "delta", "contribuicoes")
        por_elemento[elemento] = por_elemento.get(elemento, Decimal(0)) + delta
    return contribuicoes


def _conferir_atribuicao(
    delta_por_linha: Mapping[Chave, Decimal],
    contribuicoes: Mapping[Chave, Mapping[str, Decimal]],
) -> None:
    """Toda diferença precisa ter dono, e os donos precisam somar a diferença."""
    for chave, delta in delta_por_linha.items():
        declaradas = contribuicoes.get(chave, {})
        if delta and not declaradas:
            raise DecomposicaoInconsistenteError(
                f"{_descrever(chave)} mudou {_reais(delta)} e nenhum elemento assumiu a "
                "diferença"
            )
        atribuido = _somar(declaradas.values())
        # A tolerância é de um centavo inclusive: o delta vem de pontas
        # arredondadas e o atribuído não, então um centavo é aritmética. Acima
        # disso o código gerado atribuiu errado, e o número não se sustenta.
        if abs(atribuido - delta) > CENTAVO:
            raise DecomposicaoInconsistenteError(
                f"{_descrever(chave)}: os elementos somam {_reais(atribuido)}, mas a "
                f"diferença apurada é {_reais(delta)}"
            )


def _decompor(
    base: Mapping[Chave, _LinhaBase],
    delta_por_linha: Mapping[Chave, Decimal],
    contribuicoes: Mapping[Chave, Mapping[str, Decimal]],
    periodo: tuple[str, ...],
) -> Decomposicao:
    por_loja: dict[str, Decimal] = {}
    por_marca: dict[str, Decimal] = {}
    por_cargo: dict[str, Decimal] = {}
    por_competencia: dict[str, Decimal] = dict.fromkeys(periodo, Decimal(0))
    por_matricula: dict[str, Decimal] = {}
    loja_absoluto: dict[str, Decimal] = {}
    competencia_absoluto: dict[str, Decimal] = dict.fromkeys(periodo, Decimal(0))

    # Percorre todas as linhas do baseline, não só as afetadas: dimensão com
    # zero foi simulada e a regra não a alcançou, o que diz outra coisa que
    # dimensão ausente.
    for chave, linha in base.items():
        delta = delta_por_linha[chave]
        por_loja[linha.cod_loja] = por_loja.get(linha.cod_loja, Decimal(0)) + delta
        por_marca[linha.cod_marca] = por_marca.get(linha.cod_marca, Decimal(0)) + delta
        por_cargo[linha.cod_cargo] = por_cargo.get(linha.cod_cargo, Decimal(0)) + delta
        por_competencia[chave[1]] += delta
        comissao = linha.comissao + delta
        por_matricula[chave[0]] = por_matricula.get(chave[0], Decimal(0)) + comissao
        loja_absoluto[linha.cod_loja] = loja_absoluto.get(linha.cod_loja, Decimal(0)) + comissao
        competencia_absoluto[chave[1]] += comissao

    return Decomposicao(
        elemento=_por_elemento(contribuicoes),
        loja=_serializar(por_loja, _ordem_codigo),
        marca=_serializar(por_marca, _ordem_codigo),
        cargo=_serializar(por_cargo, _ordem_codigo),
        # Na ordem recebida, e com uma entrada por competência do período,
        # inclusive a que não teve nenhuma linha.
        competencia={
            competencia: _moeda(_sem_zero_negativo(por_competencia[competencia]))
            for competencia in periodo
        },
        matricula=_serializar(por_matricula, _ordem_codigo),
        loja_absoluto=_serializar(loja_absoluto, _ordem_codigo),
        competencia_absoluto={c: _moeda(competencia_absoluto[c]) for c in periodo},
    )


def _parcelas_por_linha(
    contribuicoes: Mapping[Chave, Mapping[str, Decimal]],
    delta_por_linha: Mapping[Chave, Decimal],
) -> dict[Chave, dict[str, Decimal]]:
    """Arredonda e reconcilia uma vez, para decomposição e detalhamento coincidirem."""
    por_linha: dict[Chave, dict[str, Decimal]] = {}
    for chave, declaradas in contribuicoes.items():
        parcelas = {elemento: _centavos(valor) for elemento, valor in declaradas.items()}
        # A comissão é arredondada por linha e a contribuição por elemento, e
        # ROUND_HALF_UP arredonda meio centavo para longe do zero, então as duas
        # podem divergir em um centavo na mesma linha. A sobra fica DENTRO da linha
        # que a produziu, no elemento de maior valor absoluto (empate pelo menor
        # identificador): assim o valor de um elemento nunca depende das linhas de
        # outro, e a soma dos baldes é a soma dos deltas por linha, sem resíduo.
        residuo = delta_por_linha[chave] - _somar(parcelas.values())
        if residuo:
            alvo = min(parcelas, key=lambda elemento: (-abs(parcelas[elemento]), elemento))
            parcelas[alvo] += residuo
        por_linha[chave] = parcelas
    return por_linha


def _por_elemento(contribuicoes: Mapping[Chave, Mapping[str, Decimal]]) -> dict[str, float]:
    """Preserva elementos com soma zero: efeito nulo é distinto de ausência (T-241)."""
    baldes: dict[str, Decimal] = {}
    for parcelas in contribuicoes.values():
        for elemento, valor in parcelas.items():
            baldes[elemento] = baldes.get(elemento, Decimal(0)) + valor
    return _serializar(baldes, _ordem_elemento)


def _detalhar(
    base: Mapping[Chave, _LinhaBase],
    deltas: Mapping[Chave, Decimal],
    parcelas: Mapping[Chave, Mapping[str, Decimal]],
    periodo: tuple[str, ...],
) -> LinhasResultado:
    linhas: LinhasResultado = {competencia: {} for competencia in periodo}
    for chave, linha in sorted(base.items()):
        matricula, competencia = chave
        linhas[competencia][matricula] = LinhaDetalhada(
            cod_loja=linha.cod_loja,
            cod_marca=linha.cod_marca,
            cod_cargo=linha.cod_cargo,
            comissao_baseline=_moeda(linha.comissao),
            comissao_simulada=_moeda(linha.comissao + deltas[chave]),
            diferenca=_moeda(_sem_zero_negativo(deltas[chave])),
            contribuicoes=_serializar(
                {e: v for e, v in parcelas.get(chave, {}).items() if v}, _ordem_elemento
            ),
        )
    return linhas


def _serializar(
    mapa: Mapping[str, Decimal], ordem: Callable[[str], tuple[int, int, str]]
) -> dict[str, float]:
    return {chave: _moeda(_sem_zero_negativo(mapa[chave])) for chave in sorted(mapa, key=ordem)}


def _ordem_codigo(codigo: str) -> tuple[int, int, str]:
    """Código numérico em ordem numérica: "9" antes de "13"."""
    return (0, int(codigo), "") if codigo.isdigit() else (1, 0, codigo)


def _ordem_elemento(elemento: str) -> tuple[int, int, str]:
    """Núcleo primeiro; especificações pela ordem numérica do sufixo."""
    if elemento.startswith("elem."):
        return (1, int(elemento.removeprefix("elem.")), "")
    return (0, 0, elemento)


def _linhas(tabela: Tabela, nome: str) -> list[dict[str, object]]:
    try:
        return [linha.dados for linha in _extrair_linhas(tabela, nome)]
    except RegraBaseError as erro:
        raise ResultadoInvalidoError(str(erro)) from erro


def _tabela(saida: Mapping[str, Tabela], nome: str) -> Tabela:
    if nome not in saida:
        raise ResultadoInvalidoError(f"a função gerada não devolveu {nome}")
    return saida[nome]


def _chave(registro: Registro, origem: str) -> Chave:
    return (
        _texto_de(registro, "matricula", origem),
        _texto_de(registro, "competencia", origem),
    )


def _texto_de(registro: Registro, campo: str, origem: str) -> str:
    try:
        return _texto(registro, campo, origem)
    except RegraBaseError as erro:
        raise ResultadoInvalidoError(str(erro)) from erro


def _codigo_de(registro: Registro, campo: str, origem: str) -> str:
    """Lê loja, marca ou cargo como texto: é identificador, nunca operando.

    O dataset traz inteiro e as chaves da decomposição são string, então a
    conversão acontece aqui, uma vez.
    """
    valor = _nativo(registro.get(campo))
    if isinstance(valor, bool):
        raise ResultadoInvalidoError(f"{origem}.{campo} deve ser código, não booleano")
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, str) and valor:
        return valor
    raise ResultadoInvalidoError(f"{origem}.{campo} deve ser código inteiro ou texto não vazio")


def _valor_de(registro: Registro, campo: str, origem: str) -> Decimal:
    if campo not in registro:
        raise ResultadoInvalidoError(f"{origem}.{campo} ausente")
    try:
        return numero_finito(_nativo(registro[campo]))
    except ValueError as erro:
        raise ResultadoInvalidoError(f"{origem}.{campo}: {erro}") from erro


def _nativo(valor: object) -> object:
    """Converte escalar inteiro de outra biblioteca (ex.: ``numpy.int64``) em ``int``.

    O contrato não obriga a função gerada a usar pandas, e recusar um valor
    válido por causa do tipo do escalar derrubaria um job correto.
    """
    if isinstance(valor, bool | int) or not hasattr(valor, "__index__"):
        return valor
    return operator.index(cast(SupportsIndex, valor))


def _centavos(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _sem_zero_negativo(valor: Decimal) -> Decimal:
    """``-0.00`` é zero; sair como ``-0.0`` no JSON só confunde quem lê a quebra."""
    return valor if valor else Decimal(0)


def _somar(valores: Iterable[Decimal]) -> Decimal:
    return sum(valores, Decimal(0))


def _descrever(chave: Chave) -> str:
    return f"a matrícula {chave[0]} em {chave[1]}"


def _listar(chaves: Iterable[Chave]) -> str:
    """Cita poucas chaves: mensagem de erro não é lugar para despejar dataset."""
    ordenadas = sorted(chaves)
    citadas = ", ".join(_descrever(chave) for chave in ordenadas[:MAXIMO_CHAVES_NA_MENSAGEM])
    restantes = len(ordenadas) - MAXIMO_CHAVES_NA_MENSAGEM
    return f"{citadas} e mais {restantes}" if restantes > 0 else citadas


def _reais(valor: Decimal) -> str:
    return f"R$ {_centavos(valor)}"
