import re

from app.extracao.lastro import normalizar, trecho_literal
from app.extracao.vocabulario import CampoCodigo

_DIMENSOES = {"loja": "lojas?", "marca": "marcas?", "cargo": "(?:cargos?|funcionarios?)"}


def conferir_escopo_universal(campo: CampoCodigo, trecho: object, texto: str) -> bool:
    if not trecho_literal(texto, trecho):
        return False
    assert isinstance(trecho, str)
    normalizado = normalizar(trecho)
    dimensao = _DIMENSOES[campo]
    universal = re.search(
        rf"\b(?:tod[oa]s?\s+(?:[oa]s?\s+)?{dimensao}|qualquer\s+{dimensao}|"
        rf"sem\s+(?:filtro|restricao)(?:\s+(?:de|por|para))?\s+{dimensao})\b",
        normalizado,
    )
    if universal is None or re.search(r"\b(nao|exceto|menos|salvo)\b", normalizado):
        return False
    # A citação não pode esconder a negação imediatamente anterior à expressão universal.
    for ocorrencia in re.finditer(re.escape(trecho), texto):
        prefixo = normalizar(texto[max(0, ocorrencia.start() - 45) : ocorrencia.start()])
        if not re.search(r"\bnao(?:\s+\w+){0,3}$", prefixo):
            return True
    return False
