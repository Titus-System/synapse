from collections.abc import Sequence
from contextlib import suppress
from copy import deepcopy
from typing import Any

import simplejson
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as ErroSchema
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from app.extracao.construtos.generico import montar_generico
from app.extracao.modelos import (
    ChamadaExtracao,
    FalhaExtracaoError,
    Rebaixamento,
    ResultadoExtracao,
)
from app.extracao.parametros import validar_parametros
from app.extracao.registro import CONSTRUTOS_HABILITADOS
from app.extracao.schema import schema_elemento, schema_envelope, schema_saida
from app.graph.prompts.extraction import montar_prompt_extracao
from app.representacao_regra import RepresentacaoRegra
from app.resposta_modelo import extrair_resposta
from app.tipos_estado import ValorRegra


def _objeto_sem_duplicatas(pares: list[tuple[str, Any]]) -> dict[str, Any]:
    objeto: dict[str, Any] = {}
    for chave, valor in pares:
        if chave in objeto:
            raise ValueError("Chave JSON repetida")
        objeto[chave] = valor
    return objeto


def _texto_util(valor: object) -> str | None:
    return valor if isinstance(valor, str) and valor.strip() else None


def _montar(
    conteudo: str, texto: str
) -> tuple[RepresentacaoRegra, list[Rebaixamento], dict[str, ValorRegra]]:
    rascunho = simplejson.loads(
        conteudo, use_decimal=True, allow_nan=False, object_pairs_hook=_objeto_sem_duplicatas
    )
    Draft202012Validator(schema_envelope()).validate(rascunho)
    elementos: list[dict[str, ValorRegra]] = []
    rebaixamentos: list[Rebaixamento] = []
    for indice, elemento in enumerate(rascunho["elementos"], 1):
        ref = f"elem.{indice}"
        pretendido = _texto_util(elemento.get("construto_pretendido"))
        construto = CONSTRUTOS_HABILITADOS.get(pretendido) if pretendido else None
        descricao = _texto_util(elemento.get("descricao"))
        trecho = _texto_util(elemento.get("trecho"))
        incompleto = pretendido is None or descricao is None or trecho is None
        if descricao is None:
            if trecho is None or trecho not in texto:
                raise ValueError("Elemento irrecuperável")
            descricao = trecho

        erros = list(Draft202012Validator(schema_elemento(construto)).iter_errors(elemento))
        incompleto = incompleto or any(e.validator != "additionalProperties" for e in erros)
        if construto is not None and not erros and not incompleto:
            try:
                convertido = {**construto.converter(elemento), "ref": ref, "construto": pretendido}
                # O módulo habilitado não pode contornar o contrato público da representação.
                RepresentacaoRegra.model_validate({"nucleo": {}, "especificacoes": [convertido]})
            except (ValueError, TypeError, KeyError):
                incompleto = True
            else:
                elementos.append(convertido)
                continue

        elementos.append(montar_generico(ref, descricao))
        rebaixamentos.append(
            Rebaixamento(
                ref=ref,
                construto_pretendido=pretendido,
                motivo="campo_obrigatorio_ausente" if incompleto else "construto_nao_habilitado",
            )
        )

    representacao = RepresentacaoRegra.model_validate(
        {
            "nucleo": rascunho["nucleo"],
            "especificacoes": elementos,
        }
    )
    # O trecho só serve à conferência de lastro da T-210; o valor entra como o modelo o
    # devolveu, sem checagem de lastro nesta tarefa.
    parametros = validar_parametros(
        {chave: campo["valor"] for chave, campo in rascunho["parametros"].items()}
    )
    return representacao, rebaixamentos, parametros


async def extrair_regra(
    texto: str,
    competencias: Sequence[str],
    *,
    modelo: BaseChatModel,
    metadados_modelo: dict[str, Any],
) -> ResultadoExtracao:
    if not texto.strip():
        raise FalhaExtracaoError("Texto de entrada vazio")
    schema = schema_saida(CONSTRUTOS_HABILITADOS)
    prompt = montar_prompt_extracao(
        texto, competencias, schema, [c.instrucoes for c in CONSTRUTOS_HABILITADOS.values()]
    )
    resposta = await modelo.ainvoke(
        [HumanMessage(content=prompt)],
        response_mime_type="application/json",
        response_json_schema=schema,
    )
    conteudo, motivo = extrair_resposta(resposta)
    if not conteudo.strip() or motivo != "STOP":
        raise FalhaExtracaoError("Resposta vazia, bloqueada ou interrompida")

    montado = None
    with suppress(ValueError, TypeError, ErroSchema, ValidationError, RecursionError):
        montado = _montar(conteudo, texto)
    # Fora do except para a exceção pública não reter o JSON em __context__.
    if montado is None:
        raise FalhaExtracaoError("Resposta incompatível com o schema de extração")

    consumo = None
    usage = getattr(resposta, "usage_metadata", None)
    if (
        usage
        and isinstance(usage.get("input_tokens"), int)
        and isinstance(usage.get("output_tokens"), int)
    ):
        consumo = {"tokens_in": usage["input_tokens"], "tokens_out": usage["output_tokens"]}
    representacao, rebaixamentos, parametros = montado
    return ResultadoExtracao(
        representacao=representacao,
        rebaixamentos=rebaixamentos,
        parametros=parametros,
        chamada=ChamadaExtracao(
            prompt=prompt,
            resposta=conteudo,
            modelo=deepcopy(metadados_modelo),
            consumo_tokens=consumo,
        ),
    )
