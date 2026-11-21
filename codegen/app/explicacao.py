"""Os números que a narrativa do resultado pode citar, e a conferência dela contra eles.

A narrativa cita os números da simulação e nunca os calcula (`AGENTS.md` - Security). Aqui se
monta, a partir do que o worker apurou e da regra, a lista fechada de números permitidos, já
formatados em português para o prompt; e se confere, sem modelo, que todo número do texto devolvido
corresponde a um deles. O que a conferência reprova é o número que não é nenhum dos apurados, como
a participação de uma loja na diferença, que ninguém calculou, escrita em dígitos ou por palavra.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.numeros import extrair_numeros, normalizar

# Duas casas, como o worker grava e como o usuário lê dinheiro e percentual.
_CENTAVOS = Decimal("0.01")
# Fração e múltiplo escritos por palavra são a razão entre dois apurados, e nenhuma razão está na
# lista. Cada razão é identificada pelo radical ou pelo nome da fração, para que "dobrou" e "dobro"
# sejam a mesma. "Meio" só conta antes de "por cento", porque "por meio de" não é número; "quarto"
# e "quinto" só depois de uma quantidade, porque "o quarto mês" é ordinal.
_RAZAO_POR_PALAVRA = re.compile(
    r"\b(?:(?P<radical>metade|terco|dobr|dupl|tripl|quadrupl|quintupl)\w*"
    r"|(?:um|uma|dois|duas|tres) (?P<fracao>quarto|quinto|decimo)s?"
    r"|(?P<meio>meio) por cento)\b"
)
# "Vezes" só é razão depois de um número: "dez vezes o custo", e não "às vezes". O número em si
# pode estar na lista, como a marca 10, e por isso não basta conferi-lo.
_ANTES_DE_VEZES = re.compile(r"(\S+) vezes\b")
_VEZES = "vezes"
_CODIGO_OU_DATA = re.compile(r"\d+|\d{4}-\d{2}(?:-\d{2})?")
_PERCENTUAIS_NO_EFEITO = "_pct"

#: Nome da quebra da decomposição como o prompt a apresenta. A matrícula não está aqui: ela
#: identifica pessoas e é retirada da leitura (`buscar_decomposicao`).
_QUEBRAS_DA_DIFERENCA = (
    ("elemento", "Diferença atribuída ao elemento"),
    ("loja", "Diferença na loja"),
    ("marca", "Diferença na marca"),
    ("cargo", "Diferença no cargo"),
    ("competencia", "Diferença na competência"),
)
_QUEBRAS_ABSOLUTAS = (
    ("loja_absoluto", "Comissão simulada da loja"),
    ("competencia_absoluto", "Comissão simulada da competência"),
)
_TOTAIS = (
    ("baseline", "Comissionamento atual (baseline) no período", False),
    ("simulado", "Comissionamento simulado pela regra proposta no período", False),
    ("diferenca_abs", "Diferença do simulado para o baseline", False),
    ("diferenca_pct", "Diferença percentual do simulado para o baseline", True),
    ("orcamento", "Orçamento do período", False),
    ("vendas_historicas", "Vendas históricas do período", False),
)


def formatar_reais(valor: Decimal) -> str:
    """`492100` é `R$ 492.100,00`: ponto de milhar e vírgula decimal, como se lê no Brasil."""
    arredondado = valor.quantize(_CENTAVOS, rounding=ROUND_HALF_UP)
    inteiro, _, centavos = f"{abs(arredondado):.2f}".partition(".")
    agrupado = f"{int(inteiro):,}".replace(",", ".")
    sinal = "-" if arredondado < 0 else ""
    return f"{sinal}R$ {agrupado},{centavos}"


def formatar_percentual(fracao: Decimal) -> str:
    """`0.0245` é `2,45%`: a fração do contrato lida como o usuário a escreve."""
    arredondado = (fracao * 100).quantize(_CENTAVOS, rounding=ROUND_HALF_UP)
    return f"{arredondado:.2f}".replace(".", ",") + "%"


@dataclass(frozen=True, slots=True)
class NumerosCitaveis:
    """As linhas que o prompt mostra, os valores que elas autorizam e as razões da regra.

    Os valores saem das próprias linhas, lidas pelo mesmo extrator que lê a narrativa: o que a
    lista diz e o que a conferência aceita não têm como divergir. `razoes` são as razões que o
    texto da regra escreve por palavra, como "dobrar a comissão no aniversário da loja": repeti-las
    é descrever a regra, e não fazer conta.
    """

    linhas: tuple[str, ...]
    valores: frozenset[Decimal]
    fracoes: frozenset[Decimal]
    razoes: frozenset[str]

    @classmethod
    def de_linhas(cls, linhas: Sequence[str], *, razoes: frozenset[str]) -> "NumerosCitaveis":
        # Só dígitos: as linhas são rótulos fixos e valores formatados, e uma palavra como "um" ou
        # "mil" num rótulo não pode autorizar número nenhum.
        citados = [n for linha in linhas for n in extrair_numeros(linha, por_extenso=False)]
        return cls(
            linhas=tuple(linhas),
            valores=frozenset(n.valor for n in citados if not n.percentual),
            fracoes=frozenset(n.valor for n in citados if n.percentual),
            razoes=razoes,
        )


def _razoes_por_palavra(texto: str) -> set[str]:
    """As razões que o texto escreve por palavra, cada uma pelo radical ou pelo nome da fração."""
    normalizado = normalizar(texto)
    razoes = {
        next(grupo for grupo in ocorrencia.groups() if grupo is not None)
        for ocorrencia in _RAZAO_POR_PALAVRA.finditer(normalizado)
    }
    if any(extrair_numeros(anterior[1]) for anterior in _ANTES_DE_VEZES.finditer(normalizado)):
        razoes.add(_VEZES)
    return razoes


def _textos(valor: object) -> list[str]:
    if isinstance(valor, str):
        return [valor]
    if isinstance(valor, Mapping):
        return [texto for filho in valor.values() for texto in _textos(filho)]
    if isinstance(valor, list):
        return [texto for item in valor for texto in _textos(item)]
    return []


def _percorrer_regra(
    rotulo: str, valor: object, linhas: list[str], *, percentual: bool = False
) -> None:
    """Os números estruturados de um trecho da regra, como linhas `rótulo: valor formatado`.

    Só entram números, códigos e datas: texto livre do usuário não autoriza número algum, e a
    matrícula, que tem letras, fica de fora.
    """
    if isinstance(valor, bool):
        return
    if isinstance(valor, int | float | Decimal):
        numero = Decimal(str(valor))
        formatado = formatar_percentual(numero) if percentual else formatar_reais(numero)
        linhas.append(f"{rotulo}: {formatado}")
    elif isinstance(valor, str):
        if _CODIGO_OU_DATA.fullmatch(valor):
            linhas.append(f"{rotulo}: {valor}")
    elif isinstance(valor, list):
        codigos = [
            item for item in valor if isinstance(item, str) and _CODIGO_OU_DATA.fullmatch(item)
        ]
        if codigos:
            linhas.append(f"{rotulo}: {', '.join(codigos)}")
        for item in valor:
            if isinstance(item, dict):
                _percorrer_regra(rotulo, item, linhas)
    elif isinstance(valor, dict):
        efeito_percentual = str(valor.get("tipo", "")).endswith(_PERCENTUAIS_NO_EFEITO)
        for chave, filho in valor.items():
            if chave == "ref":
                continue
            _percorrer_regra(
                f"{rotulo} / {chave}",
                filho,
                linhas,
                percentual=chave == "percentual" or (efeito_percentual and chave == "valor"),
            )


def _linhas_da_regra(regra: Mapping[str, Any]) -> list[str]:
    linhas: list[str] = []
    _percorrer_regra("Núcleo da regra", regra.get("nucleo", {}), linhas)
    for elemento in regra.get("especificacoes", []):
        ref = elemento.get("ref") if isinstance(elemento, dict) else None
        if isinstance(ref, str):
            _percorrer_regra(f"Elemento {ref}", elemento, linhas)
    return linhas


def montar_numeros_citaveis(
    *,
    totais: Mapping[str, Decimal],
    decomposicao: Mapping[str, Mapping[str, Decimal]],
    regra: Mapping[str, Any],
    competencias: Sequence[str],
    meta_venda: Decimal | None,
) -> NumerosCitaveis:
    """Todo número que a narrativa pode citar: os apurados, os da regra e os do período.

    A diferença e as quebras são as que o worker gravou; nenhuma conta é feita aqui, nem a
    participação de uma loja na diferença, que por isso não está na lista.
    """
    linhas: list[str] = []
    for nome, rotulo, percentual in _TOTAIS:
        if nome in totais:
            formatado = (
                formatar_percentual(totais[nome]) if percentual else formatar_reais(totais[nome])
            )
            linhas.append(f"{rotulo}: {formatado}")
    if meta_venda is not None:
        linhas.append(f"Meta de venda: {formatar_reais(meta_venda)}")
    # Competência escrita como AAAA-MM: o ano e o mês saem como números separados, que a
    # narrativa pode citar em qualquer formato.
    linhas.extend(f"Competência simulada: {competencia}" for competencia in competencias)
    for dimensao, rotulo in (*_QUEBRAS_DA_DIFERENCA, *_QUEBRAS_ABSOLUTAS):
        for chave, valor in decomposicao.get(dimensao, {}).items():
            linhas.append(f"{rotulo} {chave}: {formatar_reais(valor)}")
    linhas.extend(_linhas_da_regra(regra))
    textos_da_regra = _textos([regra.get("nucleo", {}), regra.get("especificacoes", [])])
    razoes = frozenset(razao for texto in textos_da_regra for razao in _razoes_por_palavra(texto))
    return NumerosCitaveis.de_linhas(linhas, razoes=razoes)


def narrativa_confere(texto: str, citaveis: NumerosCitaveis) -> bool:
    """Todo número do texto, em dígitos ou por extenso, é um dos citáveis.

    Um percentual é comparado como fração com as frações da lista, e os demais números com os
    valores dela. O sinal não conta, porque "queda de 2%" e "-2%" falam do mesmo número. Fração
    ou múltiplo por palavra, como "o dobro", "metade" ou "dez vezes", reprova o texto, porque é
    número calculado, salvo a razão que o próprio texto da regra escreve.
    """
    if not _razoes_por_palavra(texto) <= citaveis.razoes:
        return False
    return all(
        (numero.valor in citaveis.fracoes)
        if numero.percentual
        else (numero.valor in citaveis.valores)
        for numero in extrair_numeros(texto)
    )
