"""Números em português dentro de um texto: moeda, percentual, multiplicadores e extenso.

Mais de um consumidor confere números escritos por terceiros contra um valor conhecido, e todos
os leem do mesmo jeito; por isso o código mora aqui, uma vez só.
"""

import re
import unicodedata
from collections.abc import Sequence
from decimal import Decimal

NUMERO = re.compile(r"(?<![\w])[-+]?(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[,.]\d+)?)(?![\w])")
FRACAO_ANTES = re.compile(r"\bfra[cç][aã]o(?:\s+decimal)?(?:\s+de)?\s*[:=]?\s*$", re.IGNORECASE)
FRACAO_DEPOIS = re.compile(
    r"\s*(?:(?:em|como)\s+fra[cç][aã]o(?:\s+decimal)?\b|\(\s*fra[cç][aã]o(?:\s+decimal)?\s*\))",
    re.IGNORECASE,
)
MOEDA_ANTES = re.compile(r"r\$\s*\)?\s*$", re.IGNORECASE)
MOEDA_DEPOIS = re.compile(r"\s*\(?\s*(?:r\$|(?:real|reais|centavos?)\b)", re.IGNORECASE)
POR_EXTENSO = re.compile(
    r"\b(zero|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|"
    r"onze|doze|treze|catorze|quatorze|quinze|dezesseis|dezessete|dezoito|"
    r"dezenove|vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|"
    r"cem|cento|duzentos|trezentos|quatrocentos|quinhentos|seiscentos|"
    r"setecentos|oitocentos|novecentos|mil|milhao|milhoes|meio|meia)\b"
)


def normalizar(texto: str) -> str:
    sem_acentos = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caractere)
    )
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", sem_acentos.casefold())).strip()


_UNIDADES = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
}
_DEZ_A_DEZENOVE = {
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "catorze": 14,
    "quatorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
}
_DEZENAS = {
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
}
_CENTENAS = {
    "cento": 100,
    "duzentos": 200,
    "duzentas": 200,
    "trezentos": 300,
    "trezentas": 300,
    "quatrocentos": 400,
    "quatrocentas": 400,
    "quinhentos": 500,
    "quinhentas": 500,
    "seiscentos": 600,
    "seiscentas": 600,
    "setecentos": 700,
    "setecentas": 700,
    "oitocentos": 800,
    "oitocentas": 800,
    "novecentos": 900,
    "novecentas": 900,
}
_GRANDEZAS = frozenset({"mil", "milhao", "milhoes", "bilhao", "bilhoes"})


def _ate_noventa_e_nove(palavras: Sequence[str], inicio: int) -> tuple[int, int] | None:
    palavra = palavras[inicio]
    if palavra in _DEZENAS:
        fim = inicio + 1
        if fim + 1 < len(palavras) and palavras[fim] == "e" and _UNIDADES.get(palavras[fim + 1]):
            return _DEZENAS[palavra] + _UNIDADES[palavras[fim + 1]], fim + 2
        return _DEZENAS[palavra], fim
    if palavra in _DEZ_A_DEZENOVE:
        return _DEZ_A_DEZENOVE[palavra], inicio + 1
    if palavra in _UNIDADES:
        return _UNIDADES[palavra], inicio + 1
    return None


def _numero_por_extenso(palavras: Sequence[str], inicio: int) -> tuple[int, int] | None:
    palavra = palavras[inicio]
    if palavra == "cem":
        return 100, inicio + 1
    if palavra in _CENTENAS:
        fim = inicio + 1
        if fim + 1 < len(palavras) and palavras[fim] == "e":
            resto = _ate_noventa_e_nove(palavras, fim + 1)
            if resto is not None and resto[0] > 0:
                return _CENTENAS[palavra] + resto[0], resto[1]
        return _CENTENAS[palavra], fim
    return _ate_noventa_e_nove(palavras, inicio)


def numeros_por_extenso(texto: str) -> set[int]:
    """Os números de 0 a 999 escritos por extenso no texto.

    A transcrição de voz escreve os números por extenso (ADR-007), e um código de loja, marca
    ou cargo dito pelo usuário chega como "loja sessenta e oito". A leitura composta tem
    prioridade, como no português falado: "sessenta e oito" é 68, e um "e" que não compõe
    separa números, então "treze e cinquenta e oito" é 13 e 58. Um número seguido de "mil" ou
    "milhão" é uma grandeza, e não um código.
    """
    palavras = normalizar(texto).split()
    numeros: set[int] = set()
    indice = 0
    while indice < len(palavras):
        lido = _numero_por_extenso(palavras, indice)
        if lido is None:
            indice += 1
            continue
        valor, indice = lido
        if indice >= len(palavras) or palavras[indice] not in _GRANDEZAS:
            numeros.add(valor)
    return numeros


def decimal_pt(numero: str) -> Decimal:
    """O valor de um número que `NUMERO` encontrou, com a vírgula decimal e o ponto de milhar."""
    if "," in numero:
        numero = numero.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+", numero):
        numero = numero.replace(".", "")
    return Decimal(numero)


def aplicar_grandeza(valor: Decimal, depois: str) -> Decimal:
    """Multiplica o valor pela grandeza que o texto seguinte diz: "2,5 milhões", "40 mil"."""
    resto = normalizar(depois)
    if resto.startswith(("milhao", "milhoes")):
        return valor * 1_000_000
    if resto.startswith("mil"):
        return valor * 1_000
    return valor
