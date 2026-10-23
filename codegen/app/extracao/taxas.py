import re
from typing import Any

from app.extracao.lastro import conferir_numero
from app.extracao.vocabulario import FalhaCodigo, resolver_codigo
from app.tipos_estado import ValorRegra


def conferir_taxa_por_cargo(
    campo: dict[str, Any], texto: str
) -> tuple[dict[str, ValorRegra] | None, FalhaCodigo | None]:
    valor, trecho = campo["valor"], campo["trecho"]
    codigo, motivo = resolver_codigo(
        "cargo", valor["cargo"], trecho, texto, exigir_termo_conhecido=True
    )
    if codigo is None:
        return None, motivo
    percentual = valor["percentual"]
    if not conferir_numero(
        texto, trecho, percentual, percentual=True, exigir_marcador_percentual=True
    ):
        return None, "valor_sem_lastro"
    # Um trecho com taxas distintas não prova a associação: o modelo precisa citar cada par.
    percentuais = re.findall(r"[-+]?\d+(?:[,.]\d+)?\s*(?:%|por\s+cento\b)", trecho, re.I)
    if any(
        not conferir_numero(texto, citado, percentual, percentual=True) for citado in percentuais
    ):
        return None, "termo_ambiguo"
    return {"cargo": codigo, "percentual": percentual}, None
