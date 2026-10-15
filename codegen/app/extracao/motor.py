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
from app.extracao.lastro import (
    conferir_numero,
    conferir_periodo,
    trecho_literal,
)
from app.extracao.modelos import (
    ChamadaExtracao,
    FalhaExtracaoError,
    MotivoRebaixamento,
    Rebaixamento,
    ResultadoExtracao,
)
from app.extracao.montagem import consumo_de_tokens, montar_elemento, objeto_sem_duplicatas
from app.extracao.parametros import validar_parametros
from app.extracao.registro import CONSTRUTOS_HABILITADOS
from app.extracao.schema import schema_envelope, schema_saida
from app.extracao.vocabulario import carregar_vocabulario, resolver_codigo
from app.graph.prompts.extraction import montar_prompt_extracao
from app.representacao_regra import RepresentacaoRegra
from app.resposta_modelo import extrair_resposta
from app.tipos_estado import ValorRegra


def _montar(
    conteudo: str, texto: str, competencias: Sequence[str]
) -> tuple[RepresentacaoRegra, list[Rebaixamento], dict[str, ValorRegra]]:
    rascunho = simplejson.loads(
        conteudo, use_decimal=True, allow_nan=False, object_pairs_hook=objeto_sem_duplicatas
    )
    Draft202012Validator(schema_envelope()).validate(rascunho)
    elementos: list[dict[str, ValorRegra]] = []
    rebaixamentos: list[Rebaixamento] = []
    for indice, elemento in enumerate(rascunho["elementos"], 1):
        ref = f"elem.{indice}"
        convertido, rebaixamento = montar_elemento(elemento, ref, texto)
        elementos.append(convertido)
        if rebaixamento is not None:
            rebaixamentos.append(rebaixamento)

    nucleo: dict[str, ValorRegra] = {}
    rascunho_nucleo = rascunho["nucleo"]
    if "percentual" in rascunho_nucleo:
        campo = rascunho_nucleo["percentual"]
        if conferir_numero(texto, campo["trecho"], campo["valor"], percentual=True):
            nucleo["percentual"] = campo["valor"]

    def rebaixar_nucleo(trecho: str, motivo: MotivoRebaixamento) -> None:
        # Valores não resolvidos continuam visíveis para confirmação, fora do núcleo.
        referencia = f"elem.{len(elementos) + 1}"
        descricao = trecho if trecho_literal(texto, trecho) else "Critério sem lastro verificável"
        elementos.append(montar_generico(referencia, descricao))
        rebaixamentos.append(Rebaixamento(ref=referencia, motivo=motivo))

    if "vigencia" in rascunho_nucleo:
        campo = rascunho_nucleo["vigencia"]
        confere, resolvido = conferir_periodo(
            texto, campo["trecho"], campo["valor"], competencias, vigencia=True
        )
        if confere:
            nucleo["vigencia"] = campo["valor"]
        else:
            rebaixar_nucleo(
                campo["trecho"], "periodo_nao_resolvido" if not resolvido else "valor_sem_lastro"
            )

    for nome in ("loja", "marca", "cargo"):
        if nome not in rascunho_nucleo:
            continue
        aprovados: list[ValorRegra] = []
        for campo in rascunho_nucleo[nome]:
            codigo, motivo = resolver_codigo(nome, campo["valor"], campo["trecho"], texto)
            if codigo is not None:
                if codigo not in aprovados:
                    aprovados.append(codigo)
            else:
                assert motivo is not None
                rebaixar_nucleo(campo["trecho"], motivo)
        if aprovados:
            nucleo[nome] = aprovados

    representacao = RepresentacaoRegra.model_validate(
        {"nucleo": nucleo, "especificacoes": elementos}
    )
    parametros_brutos: dict[str, ValorRegra] = {}
    for nome, campo in rascunho["parametros"].items():
        if nome == "competencias":
            confere, resolvido = conferir_periodo(
                texto, campo["trecho"], campo["valor"], competencias, vigencia=False
            )
        else:
            confere = conferir_numero(texto, campo["trecho"], campo["valor"], percentual=False)
            resolvido = True
        if confere:
            parametros_brutos[nome] = campo["valor"]
        else:
            rebaixamentos.append(
                Rebaixamento(
                    ref=f"parametros.{nome}",
                    motivo="periodo_nao_resolvido" if not resolvido else "valor_sem_lastro",
                )
            )
    parametros = validar_parametros(parametros_brutos)
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
        texto,
        competencias,
        schema,
        [c.instrucoes for c in CONSTRUTOS_HABILITADOS.values()],
        carregar_vocabulario(),
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
        montado = _montar(conteudo, texto, competencias)
    # Fora do except para a exceção pública não reter o JSON em __context__.
    if montado is None:
        raise FalhaExtracaoError("Resposta incompatível com o schema de extração")

    representacao, rebaixamentos, parametros = montado
    return ResultadoExtracao(
        representacao=representacao,
        rebaixamentos=rebaixamentos,
        parametros=parametros,
        chamada=ChamadaExtracao(
            prompt=prompt,
            resposta=conteudo,
            modelo=deepcopy(metadados_modelo),
            consumo_tokens=consumo_de_tokens(resposta),
        ),
    )
