from typing import Any

from jsonschema import Draft202012Validator

from app.extracao.construtos.generico import montar_generico
from app.extracao.lastro import conferir_numero, numeros_citados, trecho_literal
from app.extracao.modelos import MotivoRebaixamento, Rebaixamento
from app.extracao.registro import CONSTRUTOS_HABILITADOS
from app.extracao.schema import schema_elemento
from app.representacao_regra import RepresentacaoRegra
from app.tipos_estado import ValorRegra


def objeto_sem_duplicatas(pares: list[tuple[str, Any]]) -> dict[str, Any]:
    objeto: dict[str, Any] = {}
    for chave, valor in pares:
        if chave in objeto:
            raise ValueError("Chave JSON repetida")
        objeto[chave] = valor
    return objeto


def consumo_de_tokens(resposta: object) -> dict[str, int] | None:
    usage = getattr(resposta, "usage_metadata", None)
    if (
        isinstance(usage, dict)
        and isinstance(usage.get("input_tokens"), int)
        and isinstance(usage.get("output_tokens"), int)
    ):
        return {"tokens_in": usage["input_tokens"], "tokens_out": usage["output_tokens"]}
    return None


def _texto_util(valor: object) -> str | None:
    return valor if isinstance(valor, str) and valor.strip() else None


def montar_elemento(
    elemento: dict[str, Any], ref: str, texto: str
) -> tuple[dict[str, ValorRegra], Rebaixamento | None]:
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
    motivo_lastro: MotivoRebaixamento | None = (
        "valor_sem_lastro" if trecho is not None and not trecho_literal(texto, trecho) else None
    )
    if (
        trecho is not None
        and trecho_literal(texto, trecho)
        and not numeros_citados(descricao).issubset(numeros_citados(trecho))
    ):
        motivo_lastro = "valor_sem_lastro"
    para_conversao = dict(elemento)
    if construto is not None and not incompleto and motivo_lastro is None:
        for chave, definicao in construto.propriedades.items():
            if definicao.get("type") not in ("number", "integer") or chave not in elemento:
                continue
            campo = elemento[chave]
            if not conferir_numero(
                texto,
                campo["trecho"],
                campo["valor"],
                percentual=chave in ("percentual", "fracao", "taxa"),
            ):
                motivo_lastro = "valor_sem_lastro"
                break
            para_conversao[chave] = campo["valor"]
    if construto is not None and not erros and not incompleto and motivo_lastro is None:
        try:
            convertido = {
                **construto.converter(para_conversao),
                "ref": ref,
                "construto": pretendido,
            }
            RepresentacaoRegra.model_validate({"nucleo": {}, "especificacoes": [convertido]})
        except (ValueError, TypeError, KeyError):
            incompleto = True
        else:
            return convertido, None

    if motivo_lastro is not None:
        descricao = (
            trecho
            if trecho is not None and trecho_literal(texto, trecho)
            else "Elemento sem lastro verificável"
        )
    return montar_generico(ref, descricao), Rebaixamento(
        ref=ref,
        construto_pretendido=pretendido,
        motivo=motivo_lastro
        or ("campo_obrigatorio_ausente" if incompleto else "construto_nao_habilitado"),
    )
