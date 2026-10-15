from collections.abc import Sequence
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from jsonschema import Draft202012Validator
from pydantic import ConfigDict, TypeAdapter

from app.extracao.modelos import FalhaExtracaoError, Rebaixamento
from app.extracao.montagem import montar_elemento
from app.extracao.parametros import validar_parametros
from app.extracao.schema_correcao import schema_envelope_correcao, schema_operacao_correcao
from app.representacao_regra import RepresentacaoRegra
from app.tipos_estado import ValorRegra


@dataclass(frozen=True, slots=True)
class DiagnosticoOperacao:
    """Diagnóstico interno, sem serialização no contrato de rebaixamentos da extração."""

    indice: int
    motivo: Literal["operacao_invalida", "referencia_inexistente"]


type DiagnosticoCorrecao = Rebaixamento | DiagnosticoOperacao
type ResultadoCorrecao = tuple[RepresentacaoRegra, dict[str, ValorRegra], list[DiagnosticoCorrecao]]

_VALOR: TypeAdapter[ValorRegra] = TypeAdapter(ValorRegra, config=ConfigDict(allow_inf_nan=False))


@dataclass(slots=True)
class _Elemento:
    ref_original: str | None
    conteudo: dict[str, ValorRegra]
    rebaixamento: Rebaixamento | None = None


def _aplicar(
    operacao: dict[str, Any],
    nucleo: dict[str, ValorRegra],
    parametros: dict[str, ValorRegra],
    elementos: list[_Elemento],
    texto: str,
) -> Literal["referencia_inexistente"] | None:
    tipo = operacao["tipo"]
    if tipo == "definir_nucleo":
        valor = _VALOR.validate_python(operacao["valor"], strict=True)
        candidato = {**nucleo, operacao["campo"]: valor}
        RepresentacaoRegra.model_validate({"nucleo": candidato, "especificacoes": []})
        nucleo[operacao["campo"]] = valor
    elif tipo == "definir_parametro":
        valor = _VALOR.validate_python(operacao["valor"], strict=True)
        validar_parametros({**parametros, operacao["campo"]: valor})
        parametros[operacao["campo"]] = valor
    elif tipo == "remover_parametro":
        parametros.pop(operacao["campo"], None)
    elif tipo == "adicionar_elemento":
        convertido, rebaixamento = montar_elemento(operacao["elemento"], "elem.1", texto)
        elementos.append(_Elemento(None, convertido, rebaixamento))
    else:
        posicao = next(
            (i for i, e in enumerate(elementos) if e.ref_original == operacao["ref"]), None
        )
        if posicao is None:
            return "referencia_inexistente"
        if tipo == "remover_elemento":
            elementos.pop(posicao)
        else:
            convertido, rebaixamento = montar_elemento(operacao["elemento"], "elem.1", texto)
            elementos[posicao] = _Elemento(operacao["ref"], convertido, rebaixamento)
    return None


def aplicar_operacoes_correcao(
    representacao: RepresentacaoRegra,
    parametros: dict[str, ValorRegra],
    operacoes: object,
    competencias_publicadas: Sequence[str],
    *,
    texto_correcao: str = "",
) -> ResultadoCorrecao:
    """Aplica um envelope desserializado; interface e diagnósticos em docs/correcao.md.

    Competências publicadas são contexto, não filtro: T-277 preserva períodos fora
    das publicadas para a validação de domínio. Não há resolução de período aqui.
    """
    if not Draft202012Validator(schema_envelope_correcao()).is_valid(operacoes):
        raise FalhaExtracaoError("Envelope de correção inválido")

    regra = deepcopy(representacao.para_contrato())
    nucleo = cast(dict[str, ValorRegra], regra["nucleo"])
    especificacoes = cast(list[dict[str, ValorRegra]], regra["especificacoes"])
    elementos = [_Elemento(cast(str, e["ref"]), e) for e in especificacoes]
    refs = [e.ref_original for e in elementos]
    if len(refs) != len(set(refs)):
        raise FalhaExtracaoError("Referências da regra atual ambíguas")
    completos = deepcopy(validar_parametros(parametros))
    envelope = cast(dict[str, Any], operacoes)
    diagnosticos: list[DiagnosticoCorrecao] = []
    # A montagem da T-203 recupera rascunhos incompletos; o envelope do item segue fechado.
    validador = Draft202012Validator(schema_operacao_correcao(validar_elemento=False))
    for indice, operacao in enumerate(envelope["operacoes"], 1):
        if not validador.is_valid(operacao):
            diagnosticos.append(DiagnosticoOperacao(indice, "operacao_invalida"))
            continue
        motivo: Literal["operacao_invalida", "referencia_inexistente"] | None = "operacao_invalida"
        with suppress(ValueError, TypeError, KeyError, RecursionError):
            motivo = _aplicar(deepcopy(operacao), nucleo, completos, elementos, texto_correcao)
        if motivo is not None:
            diagnosticos.append(DiagnosticoOperacao(indice, motivo))

    finais: list[ValorRegra] = []
    for indice, elemento in enumerate(elementos, 1):
        ref = f"elem.{indice}"
        finais.append({**elemento.conteudo, "ref": ref})
        if elemento.rebaixamento is not None:
            diagnosticos.append(replace(elemento.rebaixamento, ref=ref))
    regra["especificacoes"] = finais
    return RepresentacaoRegra.model_validate(regra), validar_parametros(completos), diagnosticos
