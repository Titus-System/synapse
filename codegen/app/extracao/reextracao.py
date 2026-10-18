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

from app.extracao.correcao import (
    DiagnosticoCorrecao,
    ResultadoCorrecao,
    aplicar_operacoes_correcao,
)
from app.extracao.modelos import ChamadaExtracao, FalhaExtracaoError
from app.extracao.montagem import consumo_de_tokens, objeto_sem_duplicatas
from app.extracao.schema_correcao import schema_operacoes_correcao
from app.graph.prompts.reextraction import montar_prompt_reextracao
from app.representacao_regra import RepresentacaoRegra
from app.resposta_modelo import extrair_resposta
from app.tipos_estado import ValorRegra


@dataclass(frozen=True, slots=True, repr=False)
class ResultadoReextracao:
    """O resultado da extração para uma correção.

    `rebaixamentos` junta `Rebaixamento` e `DiagnosticoOperacao`, que não cabe no contrato de
    rebaixamentos da extração.
    """

    representacao: RepresentacaoRegra
    parametros: dict[str, ValorRegra]
    rebaixamentos: list[DiagnosticoCorrecao]
    chamada: ChamadaExtracao


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

    Uma resposta globalmente inutilizável falha em extracao_parametros. Uma operação inválida
    ou sem lastro vira diagnóstico, sem derrubar as demais. A exceção do provedor sobe como
    veio, para `chamar_com_espera_do_provedor` classificá-la pelo tipo e pelo código.
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
    resposta = await modelo.ainvoke(
        [HumanMessage(content=prompt)],
        response_mime_type="application/json",
        response_json_schema=schema,
    )
    conteudo, motivo = extrair_resposta(resposta)
    if not conteudo.strip() or motivo != "STOP":
        raise FalhaExtracaoError("Resposta de reextração vazia, bloqueada ou interrompida")

    corrigida, completos, diagnosticos = aplicar_resposta_reextracao(
        representacao, parametros, conteudo, texto_correcao, competencias_publicadas
    )
    return ResultadoReextracao(
        representacao=corrigida,
        parametros=completos,
        rebaixamentos=diagnosticos,
        chamada=ChamadaExtracao(
            prompt=prompt,
            resposta=conteudo,
            modelo=deepcopy(metadados_modelo),
            consumo_tokens=consumo_de_tokens(resposta),
        ),
    )


def aplicar_resposta_reextracao(
    representacao: RepresentacaoRegra,
    parametros: dict[str, ValorRegra],
    conteudo: str,
    texto_correcao: str,
    competencias_publicadas: Sequence[str],
) -> ResultadoCorrecao:
    """Lê a resposta do modelo e aplica as operações, de forma determinística.

    Serve à resposta recém-recebida e à que já foi gravada, que a reexecução do nó reaplica sem
    chamar o modelo de novo (T-221). Uma resposta que não serve falha em extracao_parametros.
    """
    montado = None
    with suppress(ValueError, TypeError, KeyError, RecursionError, FalhaExtracaoError):
        operacoes = simplejson.loads(
            conteudo,
            use_decimal=True,
            allow_nan=False,
            object_pairs_hook=objeto_sem_duplicatas,
        )
        montado = aplicar_operacoes_correcao(
            representacao,
            parametros,
            operacoes,
            competencias_publicadas,
            texto_correcao=texto_correcao,
        )
    # Fora do `suppress`, para a exceção pública não reter o JSON em __context__.
    if montado is None:
        raise FalhaExtracaoError("Resposta incompatível com o schema de correção")
    return montado
