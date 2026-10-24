"""O código de uma alternativa de taxa, derivado do código já simulado da versão de origem.

A sugestão reduz as taxas da regra e mantém todo o resto (`sugestao_adaptacao.py`). O código da
versão de origem já passou no worker, então o da alternativa é o mesmo código com as taxas novas
no lugar das antigas. Pedir ao modelo um código novo para a mesma regra com outras taxas reabre
todos os erros de geração: com temperatura zero, o mesmo prompt devolve sempre o mesmo código, e
um código errado para aquelas taxas se repete em todo job com a mesma regra e o mesmo orçamento.

A troca é feita sobre a árvore sintática, só nas constantes de ponto flutuante iguais a uma taxa
antiga, e preserva o resto do texto. O código é dado não confiável: aqui ele só é lido com
`ast.parse`, nunca executado.
"""

import ast
from collections.abc import Mapping
from decimal import Decimal

from app.codigo_gerado import CodigoInvalidoError, validar_fonte
from app.tipos_estado import ValorRegra


def pares_de_taxa(origem: ValorRegra, atual: ValorRegra) -> dict[Decimal, Decimal] | None:
    """Cada taxa antiga e a nova que a substitui, quando as duas versões só diferem em números.

    None quando diferem em outra coisa, quando nada mudou, ou quando a mesma taxa antiga virou
    duas taxas novas diferentes: nesses casos o código não se deriva trocando constantes.
    """
    pares: dict[Decimal, Decimal] = {}
    if not _so_numeros_diferem(origem, atual, pares):
        return None
    return pares or None


def _so_numeros_diferem(
    origem: ValorRegra, atual: ValorRegra, pares: dict[Decimal, Decimal]
) -> bool:
    if isinstance(origem, Mapping) and isinstance(atual, Mapping):
        return origem.keys() == atual.keys() and all(
            _so_numeros_diferem(origem[chave], atual[chave], pares) for chave in origem
        )
    if isinstance(origem, list) and isinstance(atual, list):
        return len(origem) == len(atual) and all(
            _so_numeros_diferem(antes, depois, pares)
            for antes, depois in zip(origem, atual, strict=True)
        )
    if _e_numero(origem) and _e_numero(atual):
        antiga, nova = Decimal(origem), Decimal(atual)  # type: ignore[arg-type]
        return antiga == nova or pares.setdefault(antiga, nova) == nova
    return type(origem) is type(atual) and origem == atual


def _e_numero(valor: ValorRegra) -> bool:
    return not isinstance(valor, bool) and isinstance(valor, Decimal | int)


def trocar_taxas(fonte: str, pares: Mapping[Decimal, Decimal]) -> str | None:
    """O código com cada constante de taxa antiga trocada pela nova, no mesmo lugar do texto.

    None quando alguma taxa antiga não aparece como constante de ponto flutuante no código:
    escrita em percentual, como fração (`3 / 100`) ou como texto, ela não se troca sem
    interpretar o código, e a geração segue pelo modelo. Uma constante que tenha o valor de uma
    taxa antiga sem ser taxa também é trocada; a regra de comissão não tem outro número com a
    grandeza de uma taxa que coincida com ela.
    """
    try:
        modulo = ast.parse(fonte)
    except SyntaxError:
        return None
    trocas: list[tuple[int, int, int, str]] = []
    encontradas: set[Decimal] = set()
    for no in ast.walk(modulo):
        if not (isinstance(no, ast.Constant) and type(no.value) is float):
            continue
        antiga = Decimal(repr(no.value))
        if antiga not in pares or no.end_col_offset is None:
            continue
        encontradas.add(antiga)
        trocas.append((no.lineno, no.col_offset, no.end_col_offset, _literal(pares[antiga])))
    if encontradas != set(pares):
        return None

    linhas = fonte.splitlines(keepends=True)
    # As posições do `ast` são em bytes UTF-8, e uma constante numérica ocupa uma linha só. De
    # trás para a frente, uma troca não desloca as posições das que faltam na mesma linha.
    for numero, inicio, fim, literal in sorted(trocas, reverse=True):
        linha = linhas[numero - 1].encode()
        linhas[numero - 1] = (linha[:inicio] + literal.encode() + linha[fim:]).decode()
    derivada = "".join(linhas)
    try:
        validar_fonte(derivada)
    except CodigoInvalidoError:
        return None
    return derivada


def _literal(taxa: Decimal) -> str:
    texto = format(taxa.normalize(), "f")
    return texto if "." in texto else f"{texto}.0"
