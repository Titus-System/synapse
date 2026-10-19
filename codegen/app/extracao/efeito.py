"""Efeito de `comum.schema.json`, normalizado para os construtos que o carregam."""

import re
from typing import Any

from app.extracao.construto import com_lastro
from app.extracao.lastro import conferir_numero
from app.extracao.modelos import ElementoRebaixadoError
from app.tipos_estado import ValorRegra

# `acrescimo_base` não tem definição no projeto, então fica fora do rascunho: um efeito que só
# caberia nele não passa no schema e rebaixa o elemento.
TIPOS_PERCENTUAIS = ("acrescimo_pct", "substituicao_pct")
TIPO_MONETARIO = "bonus_fixo"

SCHEMA_EFEITO: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tipo", "valor"],
    "properties": {
        "tipo": {"type": "string", "enum": [*TIPOS_PERCENTUAIS, TIPO_MONETARIO]},
        "valor": com_lastro({"type": "number"}),
    },
}

_PERCENTUAL = re.compile(r"%|\bpor\s+cento\b|\bpercentual\b", re.IGNORECASE)


def _seguido_de_percentual(valor: str, trecho: str) -> bool:
    return any(
        re.match(r"\s*(?:%|por\s+cento\b)", trecho[achado.end() :], re.IGNORECASE)
        for achado in re.finditer(re.escape(valor), trecho)
    )


def valor_monetario(
    campo: dict[str, Any], texto: str, trecho_elemento: str | None = None
) -> ValorRegra:
    if not conferir_numero(texto, campo["trecho"], campo["valor"], percentual=False):
        raise ElementoRebaixadoError("valor_sem_lastro")
    # O valor do bônus é em reais; um percentual não tem como virar o valor do contrato, nem
    # quando o trecho do valor omite o símbolo que o trecho do elemento traz.
    trecho = trecho_elemento if trecho_elemento is not None else texto
    if _PERCENTUAL.search(campo["trecho"]) or _seguido_de_percentual(campo["trecho"], trecho):
        raise ElementoRebaixadoError("campo_obrigatorio_ausente")
    valor: ValorRegra = campo["valor"]
    return valor


def _fracao(campo: dict[str, Any], texto: str) -> ValorRegra:
    # Sem o marcador de percentual no trecho, o número poderia ser reais ou outra grandeza.
    if not _PERCENTUAL.search(campo["trecho"]) or not conferir_numero(
        texto, campo["trecho"], campo["valor"], percentual=True
    ):
        raise ElementoRebaixadoError("valor_sem_lastro")
    valor: ValorRegra = campo["valor"]
    return valor


def normalizar_efeito(rascunho: dict[str, Any], texto: str) -> dict[str, ValorRegra]:
    tipo = rascunho["tipo"]
    valor = (
        valor_monetario(rascunho["valor"], texto)
        if tipo == TIPO_MONETARIO
        else _fracao(rascunho["valor"], texto)
    )
    return {"tipo": tipo, "valor": valor}
