"""Chamada isolada ao modelo para reextrair correções (T-220).

A aplicação das operações é pura e fica em correcao.py. Nenhuma operação de
banco, grafo, broker ou ferramenta é executada aqui.
"""

from collections.abc import Mapping, Sequence
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import simplejson
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.extracao.correcao import DiagnosticoCorrecao, aplicar_operacoes_correcao
from app.extracao.modelos import ChamadaExtracao, FalhaExtracaoError
from app.extracao.schema_correcao import schema_operacoes_correcao
from app.graph.prompts.reextraction import montar_prompt_reextracao
from app.representacao_regra import RepresentacaoRegra
from app.resposta_modelo import extrair_resposta
from app.tipos_estado import ValorRegra


@dataclass(frozen=True, slots=True, repr=False)
class ResultadoReextracao:
    """Resultado equivalente à extração, com diagnósticos locais ainda não persistíveis."""

    representacao: RepresentacaoRegra
    parametros: dict[str, ValorRegra]
    rebaixamentos: list[DiagnosticoCorrecao]
    chamada: ChamadaExtracao


class FalhaChamadaReextracaoError(RuntimeError):
    """Falha transitória sanitizada; não retém exceção, prompt ou resposta."""


def _objeto_sem_duplicatas(pares: list[tuple[str, Any]]) -> dict[str, Any]:
    objeto: dict[str, Any] = {}
    for chave, valor in pares:
        if chave in objeto:
            raise ValueError("Chave JSON repetida")
        objeto[chave] = valor
    return objeto


def _consumo_tokens(resposta: object) -> dict[str, int] | None:
    usage = getattr(resposta, "usage_metadata", None)
    if (
        isinstance(usage, dict)
        and isinstance(usage.get("input_tokens"), int)
        and isinstance(usage.get("output_tokens"), int)
    ):
        return {"tokens_in": usage["input_tokens"], "tokens_out": usage["output_tokens"]}
    return None


async def reextrair_regra(
    representacao: RepresentacaoRegra,
    parametros: dict[str, ValorRegra],
    conflitos: Sequence[Mapping[str, object]],
    texto_correcao: str,
    competencias_publicadas: Sequence[str],
    *,
    modelo: BaseChatModel,
    metadados_modelo: dict[str, Any],
) -> ResultadoReextracao:
    """Produz operações com uma chamada sem ferramentas e aplica-as deterministicamente.

    Uma resposta globalmente inutilizável falha em extracao_parametros. Operações
    individualmente inválidas são diagnosticadas pelo aplicador da etapa 1.
    """
    if not texto_correcao.strip():
        raise FalhaExtracaoError("Texto de correção vazio")

    schema = schema_operacoes_correcao()
    prompt = montar_prompt_reextracao(
        representacao,
        parametros,
        conflitos,
        texto_correcao,
        competencias_publicadas,
        schema=schema,
    )
    resposta = None
    # O provider pode incluir dados privados no erro; a falha pública não o encadeia.
    with suppress(Exception):
        resposta = await modelo.ainvoke(
            [HumanMessage(content=prompt)],
            response_mime_type="application/json",
            response_json_schema=schema,
        )
    if resposta is None:
        raise FalhaChamadaReextracaoError("Falha ao chamar o modelo de reextração")

    conteudo, motivo = extrair_resposta(resposta)
    if not conteudo.strip() or motivo != "STOP":
        raise FalhaExtracaoError("Resposta de reextração vazia, bloqueada ou interrompida")

    montado = None
    with suppress(ValueError, TypeError, KeyError, RecursionError, FalhaExtracaoError):
        operacoes = simplejson.loads(
            conteudo,
            use_decimal=True,
            allow_nan=False,
            object_pairs_hook=_objeto_sem_duplicatas,
        )
        montado = aplicar_operacoes_correcao(
            representacao,
            parametros,
            operacoes,
            competencias_publicadas,
            texto_correcao=texto_correcao,
        )
    if montado is None:
        raise FalhaExtracaoError("Resposta incompatível com o schema de correção")

    corrigida, completos, diagnosticos = montado
    return ResultadoReextracao(
        representacao=corrigida,
        parametros=completos,
        rebaixamentos=diagnosticos,
        chamada=ChamadaExtracao(
            prompt=prompt,
            resposta=conteudo,
            modelo=deepcopy(metadados_modelo),
            consumo_tokens=_consumo_tokens(resposta),
        ),
    )
