"""Conferências determinísticas do trecho original, independentes da resposta do modelo."""

import re
import unicodedata
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import pairwise

_MESES = (
    "janeiro",
    "fevereiro",
    "marco",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
_NUMERO = re.compile(r"(?<![\w])[-+]?(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[,.]\d+)?)(?![\w])")
_FRACAO_ANTES = re.compile(r"\bfra[cç][aã]o(?:\s+decimal)?(?:\s+de)?\s*[:=]?\s*$", re.IGNORECASE)
_FRACAO_DEPOIS = re.compile(
    r"\s*(?:(?:em|como)\s+fra[cç][aã]o(?:\s+decimal)?\b|\(\s*fra[cç][aã]o(?:\s+decimal)?\s*\))",
    re.IGNORECASE,
)
_MOEDA_ANTES = re.compile(r"r\$\s*\)?\s*$", re.IGNORECASE)
_MOEDA_DEPOIS = re.compile(r"\s*\(?\s*(?:r\$|(?:real|reais|centavos?)\b)", re.IGNORECASE)
_POR_EXTENSO = re.compile(
    r"\b(zero|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|"
    r"onze|doze|treze|catorze|quatorze|quinze|dezesseis|dezessete|dezoito|"
    r"dezenove|vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|"
    r"cem|cento|duzentos|trezentos|quatrocentos|quinhentos|seiscentos|"
    r"setecentos|oitocentos|novecentos|mil|milhao|milhoes|meio|meia)\b"
)
_COMPETENCIA = re.compile(r"(?<!\d)(\d{4})-(0[1-9]|1[0-2])(?!\d)")
_COMPETENCIA_BR = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])/(19\d{2}|20\d{2})(?!\d)")
_MES = re.compile(r"\b(" + "|".join(_MESES) + r")\b")
_ANO = re.compile(r"\b(?:19|20)\d{2}\b")
_DATA_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_DATA_BR = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?:/(\d{4}))?(?![\d/])")
_DATA_EXTENSO = re.compile(r"(?<!\d)(\d{1,2}) de (" + "|".join(_MESES) + r")(?: de (\d{4}))?(?!\d)")


def normalizar(texto: str) -> str:
    sem_acentos = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caractere)
    )
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", sem_acentos.casefold())).strip()


def trecho_literal(texto: str, trecho: object) -> bool:
    return isinstance(trecho, str) and bool(trecho.strip()) and trecho in texto


def numeros_citados(texto: str) -> set[str]:
    return {ocorrencia.group() for ocorrencia in _NUMERO.finditer(texto)}


def _decimal(numero: str) -> Decimal:
    if "," in numero:
        numero = numero.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+", numero):
        numero = numero.replace(".", "")
    return Decimal(numero)


def _numero_monetario(texto: str, trecho: str, numero: re.Match[str]) -> bool:
    for evidencia in re.finditer(re.escape(trecho), texto):
        antes = texto[: evidencia.start() + numero.start()]
        depois = texto[evidencia.start() + numero.end() :]
        indicacao_fracao = _FRACAO_DEPOIS.match(depois)
        if indicacao_fracao is not None:
            depois = depois[indicacao_fracao.end() :]
        if _MOEDA_ANTES.search(antes) or _MOEDA_DEPOIS.match(depois):
            return True
    return False


def conferir_numero(
    texto: str,
    trecho: object,
    valor: object,
    *,
    percentual: bool,
    exigir_marcador_percentual: bool = False,
) -> bool:
    if not trecho_literal(texto, trecho) or isinstance(valor, bool):
        return False
    try:
        esperado = Decimal(str(valor))
        if not esperado.is_finite():
            return False
    except (ValueError, InvalidOperation, TypeError):
        return False
    assert isinstance(trecho, str)
    ocorrencias = list(_NUMERO.finditer(trecho))
    if not ocorrencias:
        if exigir_marcador_percentual:
            for marcador in re.finditer(r"%|\bpor\s+cento\b", trecho, flags=re.IGNORECASE):
                palavras = normalizar(trecho[: marcador.start()]).split()
                if palavras and _POR_EXTENSO.fullmatch(palavras[-1]):
                    return True
            return False
        # Número por extenso: somente a existência literal é verificável (T-210).
        return bool(_POR_EXTENSO.search(normalizar(trecho)))
    for ocorrencia in ocorrencias:
        encontrado = _decimal(ocorrencia.group())
        if percentual:
            if exigir_marcador_percentual and _numero_monetario(texto, trecho, ocorrencia):
                continue
            if re.match(r"\s*(?:%|por\s+cento\b)", trecho[ocorrencia.end() :], flags=re.IGNORECASE):
                encontrado /= 100
            elif exigir_marcador_percentual:
                antes = trecho[: ocorrencia.start()].rstrip()
                depois = trecho[ocorrencia.end() :].lstrip()
                if (
                    antes.endswith("/")
                    or depois.startswith("/")
                    or not (_FRACAO_ANTES.search(antes) or _FRACAO_DEPOIS.match(depois))
                ):
                    continue
                # A fração explícita pode usar ponto decimal, como 0.025, sem agrupar milhares.
                if re.fullmatch(r"[-+]?\d+\.\d+", ocorrencia.group()):
                    encontrado = Decimal(ocorrencia.group())
        else:
            resto = normalizar(trecho[ocorrencia.end() :])
            if resto.startswith(("milhao", "milhoes")):
                encontrado *= 1_000_000
            elif resto.startswith("mil"):
                encontrado *= 1_000
        if encontrado == esperado:
            return True
    return False


def _meses_inclusivos(inicio: str, fim: str, *, vigencia: bool = False) -> list[str] | None:
    a, b = (int(inicio[:4]) * 12 + int(inicio[5:]) - 1, int(fim[:4]) * 12 + int(fim[5:]) - 1)
    if a > b:
        return [inicio, fim] if vigencia else None
    if b - a > 120:
        return None
    return [f"{numero // 12:04d}-{numero % 12 + 1:02d}" for numero in range(a, b + 1)]


def resolver_periodo(
    trecho: str, publicadas: Sequence[str], *, vigencia: bool = False
) -> list[str] | None:
    """Extrai somente meses presentes no trecho; o ano implícito vem do job."""
    normalizado = normalizar(trecho)
    iso = list(_COMPETENCIA.finditer(trecho))
    brasileiro = list(_COMPETENCIA_BR.finditer(trecho))
    por_nome = list(_MES.finditer(normalizado))
    if sum(bool(formato) for formato in (iso, brasileiro, por_nome)) != 1:
        return None
    base = trecho
    if iso:
        referencias = iso
        meses = [f"{item[1]}-{item[2]}" for item in iso]
    elif brasileiro:
        referencias = brasileiro
        meses = [f"{item[2]}-{int(item[1]):02d}" for item in brasileiro]
    else:
        base = normalizado
        referencias = por_nome
        anos = set(_ANO.findall(normalizado))
        if not anos:
            anos = {c[:4] for c in publicadas if _COMPETENCIA.fullmatch(c)}
        if len(anos) != 1:
            return None
        ano = anos.pop()
        meses = [f"{ano}-{_MESES.index(item.group()) + 1:02d}" for item in referencias]

    ligacoes = [base[a.end() : b.start()] for a, b in pairwise(referencias)]
    intervalo = any(
        re.search(r"\b(?:a|ate)$", normalizar(ligacao))
        or ligacao.strip() in ("-", "\u2013", "\u2014")
        for ligacao in ligacoes
    ) or bool(re.search(r"\bentre\s*$", normalizar(base[: referencias[0].start()])))
    if len(meses) == 2 and re.search(r"\s[-\u2013\u2014]\s", trecho):
        intervalo = True
    if intervalo:
        if len(meses) != 2:
            return None
        return _meses_inclusivos(meses[0], meses[-1], vigencia=vigencia)
    if vigencia and len(meses) > 1:
        return None
    return sorted(set(meses))


def conferir_periodo(
    texto: str, trecho: object, valor: object, publicadas: Sequence[str], *, vigencia: bool
) -> tuple[bool, bool]:
    """Retorna (confere, resolvido); ausência de ano ambíguo não é lastro numérico."""
    if not trecho_literal(texto, trecho):
        return False, True
    assert isinstance(trecho, str)
    periodo = resolver_periodo(trecho, publicadas, vigencia=vigencia)
    if periodo is None:
        return False, False
    if vigencia:
        return isinstance(valor, dict) and valor == {"inicio": periodo[0], "fim": periodo[-1]}, True
    return isinstance(valor, list) and valor == periodo, True


def _data_valida(ano: int, mes: int, dia: int) -> str | None:
    try:
        return date(ano, mes, dia).isoformat()
    except ValueError:
        return None


def resolver_datas(trecho: str, publicadas: Sequence[str]) -> list[str] | None:
    """Datas AAAA-MM-DD do trecho, na ordem em que aparecem; None se o ano não se resolve.

    O ano que o trecho não diz é o ano comum das competências do job. Datas escritas em mais de
    um formato no mesmo trecho não têm ordem confiável e também resultam em None.
    """
    por_formato: list[list[tuple[int | None, int, int]]] = [
        [(int(a), int(m), int(d)) for a, m, d in _DATA_ISO.findall(trecho)],
        [(int(a) if a else None, int(m), int(d)) for d, m, a in _DATA_BR.findall(trecho)],
        [
            (int(a) if a else None, _MESES.index(m) + 1, int(d))
            for d, m, a in _DATA_EXTENSO.findall(normalizar(trecho))
        ],
    ]
    encontradas = [formato for formato in por_formato if formato]
    if not encontradas:
        return []
    if len(encontradas) > 1:
        return None
    anos = {c[:4] for c in publicadas if _COMPETENCIA.fullmatch(c)}
    datas: list[str] = []
    for ano, mes, dia in encontradas[0]:
        if ano is None:
            if len(anos) != 1:
                return None
            ano = int(next(iter(anos)))
        # Descartar só a data inválida faria um intervalo incompleto parecer um dia único.
        resolvida = _data_valida(ano, mes, dia)
        if resolvida is None:
            return []
        datas.append(resolvida)
    return datas


def conferir_data(
    texto: str, trecho: object, valor: object, publicadas: Sequence[str]
) -> tuple[bool, bool]:
    """Retorna (confere, resolvido) para uma única data, como `conferir_periodo`."""
    if not trecho_literal(texto, trecho):
        return False, True
    assert isinstance(trecho, str)
    datas = resolver_datas(trecho, publicadas)
    if datas is None:
        return False, False
    return len(datas) == 1 and valor == datas[0], True
