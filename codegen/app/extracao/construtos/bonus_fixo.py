import re
from typing import Any

from app.extracao.construto import Construto, ContextoExtracao, com_lastro
from app.extracao.lastro import conferir_data, conferir_numero
from app.extracao.modelos import ElementoRebaixadoError
from app.extracao.vocabulario import resolver_codigo
from app.tipos_estado import ValorRegra

_TEXTO = {"type": "string", "minLength": 1}
_DATA = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}

# O contrato só descreve o filtro como um objeto de critérios cadastrais. As chaves aceitas são
# as dos seus exemplos; outra chave não cabe no schema do rascunho e rebaixa o elemento.
_CRITERIOS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"cargo": _TEXTO, "admitido_ate": _DATA},
}

_PERCENTUAL = re.compile(r"%|\bpor\s+cento\b|\bpercentual\b", re.IGNORECASE)
_MATRICULA_INFORMADA = re.compile(r"(?:MATRIC-)?(\d+)", re.IGNORECASE)
_MATRICULA_CANONICA = re.compile(r"(?<![\w-])MATRIC-(\d+)(?!\w)", re.IGNORECASE)
_MATRICULAS_APOS_PALAVRA = re.compile(
    r"\bmatr[ií]culas?\s+(\d+(?:\s*(?:,|\be\b|\bou\b)\s*\d+)*)", re.IGNORECASE
)


def _numeros_de_matricula(trecho: str) -> set[str]:
    numeros = set(_MATRICULA_CANONICA.findall(trecho))
    for lista in _MATRICULAS_APOS_PALAVRA.findall(trecho):
        numeros.update(re.findall(r"\d+", lista))
    return numeros


def _valor_monetario(campo: dict[str, Any], texto: str) -> ValorRegra:
    if not conferir_numero(texto, campo["trecho"], campo["valor"], percentual=False):
        raise ElementoRebaixadoError("valor_sem_lastro")
    # O valor do bônus é em reais; um percentual não tem como virar o valor do contrato.
    if _PERCENTUAL.search(campo["trecho"]):
        raise ElementoRebaixadoError("campo_obrigatorio_ausente")
    valor: ValorRegra = campo["valor"]
    return valor


def _matriculas(informadas: list[str], trecho: str) -> list[ValorRegra]:
    # Só entra a matrícula que o trecho cita; o motor não consulta o cadastro.
    citadas = _numeros_de_matricula(trecho)
    aprovadas: list[ValorRegra] = []
    for informada in informadas:
        formato = _MATRICULA_INFORMADA.fullmatch(informada.strip())
        if formato is None or formato[1] not in citadas:
            continue
        matricula = f"MATRIC-{formato[1]}"
        if matricula not in aprovadas:
            aprovadas.append(matricula)
    if not aprovadas:
        raise ElementoRebaixadoError("valor_sem_lastro")
    return aprovadas


def _filtro(
    criterios: dict[str, Any], trecho: str, contexto: ContextoExtracao
) -> dict[str, ValorRegra]:
    filtro: dict[str, ValorRegra] = {}
    if "cargo" in criterios:
        codigo, motivo = resolver_codigo("cargo", criterios["cargo"], trecho, contexto.texto)
        if codigo is None:
            assert motivo is not None
            raise ElementoRebaixadoError(motivo)
        filtro["cargo"] = codigo
    if "admitido_ate" in criterios:
        confere, resolvido = conferir_data(
            contexto.texto, trecho, criterios["admitido_ate"], contexto.competencias
        )
        if not confere:
            raise ElementoRebaixadoError(
                "valor_sem_lastro" if resolvido else "periodo_nao_resolvido"
            )
        filtro["admitido_ate"] = criterios["admitido_ate"]
    return filtro


def converter(rascunho: dict[str, Any], contexto: ContextoExtracao) -> dict[str, ValorRegra]:
    valor = _valor_monetario(rascunho["valor"], contexto.texto)
    # O alvo declarado tem de ser o único presente; um rascunho com os dois não é representável.
    if rascunho["tipo_alvo"] == "lista" and "criterios" not in rascunho:
        alvo: ValorRegra = _matriculas(rascunho["matriculas"], rascunho["trecho"])
    elif rascunho["tipo_alvo"] == "filtro" and "matriculas" not in rascunho:
        alvo = _filtro(rascunho["criterios"], rascunho["trecho"], contexto)
        if not alvo:
            raise ValueError("Filtro sem critério")
    else:
        raise ValueError("Alvo inconsistente")
    return {"alvo": {"tipo": rascunho["tipo_alvo"], "valor": alvo}, "valor": valor}


BONUS_FIXO = Construto(
    propriedades={
        "tipo_alvo": {"type": "string", "enum": ["lista", "filtro"]},
        "matriculas": {"type": "array", "minItems": 1, "items": _TEXTO},
        "criterios": _CRITERIOS,
        "valor": com_lastro({"type": "number"}),
    },
    obrigatorios=("tipo_alvo", "valor"),
    instrucoes=(
        "bonus_fixo: valor em reais concedido a um alvo, uma vez por competência. "
        "tipo_alvo 'lista': matriculas no formato MATRIC-<número> (matrícula 422 vira "
        "MATRIC-422), só as que o texto cita. "
        "tipo_alvo 'filtro': criterios com cargo (código) e/ou admitido_ate (AAAA-MM-DD). "
        "valor é {valor, trecho} em reais (R$ 1.000 e 'mil reais' viram 1000). Na descricao, "
        "mantenha as datas como o texto as escreve (10/10), sem convertê-las. "
        "Exemplos: 'bônus fixo de R$ 500 para as matrículas MATRIC-422 e MATRIC-517' -> lista; "
        "'os admitidos até 10/10 no cargo 100 terão bônus de R$ 1.000' -> filtro. "
        "Bônus em percentual, sem alvo identificável, por faixa de venda ou com outro critério "
        "de filtro (loja, marca) é generico."
    ),
    converter=converter,
)
