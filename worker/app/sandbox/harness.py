"""Harness do sandbox (T-033): carrega a função gerada, chama e agrega o resultado.

Este é o único módulo que compila e executa código gerado, e só pode rodar dentro do
container efêmero da imagem do sandbox (``worker/AGENTS.md``). Nenhum caminho de
código do processo do worker o importa; ``test_isolamento_harness.py`` prova isso.

A função gerada e o harness rodam no mesmo processo Python (contrato T-034): o modelo
não dá isolamento, a contenção vem das flags do container. O que este módulo faz é
impedir o erro acidental: a regra recebe cópias das entradas, e a agregação usa o
baseline que só o harness guarda.
"""

from __future__ import annotations

import linecache
import sys
import types
from collections.abc import Callable, Mapping, Sequence
from typing import NamedTuple, cast

import pandas

from app.sandbox.assercoes import Desfecho, numero_finito
from app.sandbox.carga import Entrada
from app.sandbox.regras_base import Registro
from app.sandbox.resultado import ResultadoSimulacao, montar_resultado

NOME_ARQUIVO = "regra.py"
NOME_MODULO = "regra"

# O mesmo nome que a T-031 usa em finalizar_apuracao; um teste confere.
NOME_SEM_COMISSAO_NEGATIVA = "sem_comissao_negativa"
MAXIMO_VIOLACOES_NO_DETALHE = 5

# Colunas que o contrato exige em cada tabela devolvida. Colunas a mais são ignoradas:
# a agregação só lê o que o contrato define e a saída não carrega linha de base.
COLUNAS_EXIGIDAS: Mapping[str, tuple[str, ...]] = {
    "apuracao_simulada": (
        "matricula",
        "cod_loja",
        "cod_marca",
        "cod_cargo",
        "competencia",
        "comissao",
    ),
    "contribuicoes": (
        "matricula",
        "cod_loja",
        "cod_marca",
        "cod_cargo",
        "competencia",
        "elemento_ref",
        "delta",
    ),
}

type RegraFn = Callable[
    [dict[str, pandas.DataFrame], pandas.DataFrame, list[str]],
    dict[str, pandas.DataFrame],
]


class RegraInvalidaError(ValueError):
    """O código gerado não compila ou não expõe ``aplicar_regra``."""


class SaidaForaDoContratoError(ValueError):
    """O retorno da função gerada não é o que o contrato da T-034 define."""


class Execucao(NamedTuple):
    assercoes: list[Desfecho]
    # Só quando nenhuma asserção foi violada: número inválido não vira resultado.
    resultado: ResultadoSimulacao | None


def carregar_regra(fonte: str, *, nome_arquivo: str = NOME_ARQUIVO) -> RegraFn:
    """Compila e executa a fonte num módulo em memória, e devolve ``aplicar_regra``.

    Nada é escrito em disco: com ``--read-only`` e sem volume não haveria onde. O
    ``linecache`` é semeado porque, sem arquivo, o traceback que chega ao usuário
    sairia sem a linha ofensora.
    """
    try:
        # dont_inherit: sem isso o código herdaria ``from __future__ import annotations``
        # deste arquivo, e a regra rodaria com semântica de anotação que não escolheu.
        codigo = compile(fonte, nome_arquivo, "exec", dont_inherit=True)
    except (SyntaxError, ValueError) as erro:
        raise RegraInvalidaError(f"o código gerado não compila: {erro}") from erro

    linecache.cache[nome_arquivo] = (len(fonte), None, fonte.splitlines(True), nome_arquivo)
    modulo = types.ModuleType(NOME_MODULO)
    modulo.__file__ = nome_arquivo
    # Registrado porque dataclasses, typing.get_type_hints e pickle consultam
    # sys.modules[cls.__module__]; sem isso um @dataclass na regra falha com
    # AttributeError por um motivo que não tem nada a ver com a regra.
    sys.modules[NOME_MODULO] = modulo
    # A execução da regra é a razão de existir deste módulo. Só roda dentro do
    # container efêmero, sem rede e somente-leitura; o isolamento é do container.
    exec(codigo, modulo.__dict__)  # nosec B102
    regra = getattr(modulo, "aplicar_regra", None)
    if not callable(regra):
        raise RegraInvalidaError("o código gerado não define aplicar_regra")
    return cast(RegraFn, regra)


def preparar(bases: Mapping[str, pandas.DataFrame]) -> dict[str, pandas.DataFrame]:
    """Cópias das bases, para a função gerada não alterar as do harness."""
    return {nome: tabela.copy(deep=True) for nome, tabela in bases.items()}


def chamar(
    regra: RegraFn,
    bases: Mapping[str, pandas.DataFrame],
    apuracao_base: pandas.DataFrame,
    competencias: Sequence[str],
) -> dict[str, pandas.DataFrame]:
    """Chama a regra com cópias de tudo. É a única linha que executa código gerado.

    A lista de competências também é copiada: ela chega "como veio", mas uma regra que
    a alterasse não pode mudar o período que o harness usa depois.
    """
    return regra(preparar(bases), apuracao_base.copy(deep=True), list(competencias))


def conferir_saida(saida: object) -> dict[str, pandas.DataFrame]:
    """O retorno precisa ser um dict com as duas tabelas e as colunas do contrato."""
    if not isinstance(saida, dict):
        raise SaidaForaDoContratoError(
            f"a função gerada devolveu {type(saida).__name__}, não um dict"
        )
    for nome, colunas in COLUNAS_EXIGIDAS.items():
        tabela = saida.get(nome)
        if not isinstance(tabela, pandas.DataFrame):
            raise SaidaForaDoContratoError(
                f"{nome} deve ser um DataFrame, não {type(tabela).__name__}"
            )
        ausentes = [coluna for coluna in colunas if coluna not in tabela.columns]
        if ausentes:
            raise SaidaForaDoContratoError(f"{nome} não tem as colunas {ausentes}")
    return cast(dict[str, pandas.DataFrame], saida)


def rodar_regra(
    fonte: str, entrada: Entrada, competencias: Sequence[str]
) -> dict[str, pandas.DataFrame]:
    """Tudo que executa ou confere a função gerada. Qualquer falha aqui é do código gerado."""
    regra = carregar_regra(fonte)
    return conferir_saida(chamar(regra, entrada.bases, entrada.apuracao_base, competencias))


def comissao_nao_negativa(linhas: Sequence[Registro]) -> Desfecho:
    """A invariante ``sem_comissao_negativa`` da T-031 sobre a apuração simulada.

    Roda só esta das três: ``soma_loja_igual_soma_matricula`` compara as linhas com um
    acumulador de lojas produzido durante o cálculo pelo motor da T-030, e derivá-lo das
    próprias linhas simuladas compara a soma com ela mesma; ``sem_comissao_sem_venda``
    exige as origens declaradas, que a representação da regra (fora do container)
    informaria, e sem elas reprovaria uma regra legítima de bônus fixo. A comissão sem
    dono é coberta pela agregação, que recusa toda diferença sem elemento que a assuma.
    """
    violacoes: list[str] = []
    for linha in linhas:
        ponto = f"{linha.get('competencia')}, matrícula {linha.get('matricula')}"
        try:
            valor = numero_finito(linha.get("comissao"))
        except ValueError as erro:
            violacoes.append(f"{ponto}: {erro}")
            continue
        if valor < 0:
            violacoes.append(f"{ponto}: comissão {valor} negativa")

    if not violacoes:
        return {"nome": NOME_SEM_COMISSAO_NEGATIVA, "resultado": "ok", "detalhe": None}
    citadas = violacoes[:MAXIMO_VIOLACOES_NO_DETALHE]
    restantes = len(violacoes) - len(citadas)
    detalhe = "; ".join(citadas) + (f"; e mais {restantes}" if restantes else "")
    return {"nome": NOME_SEM_COMISSAO_NEGATIVA, "resultado": "violada", "detalhe": detalhe}


def agregar(
    saida: Mapping[str, pandas.DataFrame], entrada: Entrada, competencias: Sequence[str]
) -> Execucao:
    """Confere a asserção e agrega o resultado.

    O baseline que vai para a agregação é ``entrada.registros_base``, que o harness
    guarda e a regra nunca recebeu. Se fosse o mesmo objeto entregue à regra, uma regra
    que rebaixasse o baseline recebido produziria economia inventada com tudo
    reconciliando: nenhuma exceção, nenhuma asserção violada, número errado com
    aparência de certo.
    """
    simulada = _registros(saida["apuracao_simulada"])
    desfecho = comissao_nao_negativa(simulada)
    if desfecho["resultado"] == "violada":
        return Execucao([desfecho], None)
    resultado = montar_resultado(
        {"apuracao_simulada": simulada, "contribuicoes": _registros(saida["contribuicoes"])},
        entrada.registros_base,
        competencias,
        assercoes=[desfecho],
    )
    return Execucao([desfecho], resultado)


def _registros(tabela: pandas.DataFrame) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], tabela.to_dict(orient="records"))
