import re
from typing import Any

from app.extracao.construto import Construto, ContextoExtracao, com_lastro
from app.extracao.efeito import valor_monetario
from app.extracao.lastro import conferir_data, normalizar
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

# Negação e exceção invertem ou restringem o alvo, que o conversor só lê pelas matrículas citadas.
_NEGACAO = re.compile(r"\b(?:nao|nunca|nem|sem|exceto|salvo|ninguem|demais)\b")
# O filtro só tem admitido_ate, que inclui o dia; outra direção seria o alvo oposto.
_ATE = re.compile(r"\bate\b")
_OUTRA_DIRECAO = re.compile(
    r"\b(?:a partir de|depois de|apos|desde|antes de|anteriores? a|posteriores? a)\b"
)
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
        frase = normalizar(trecho)
        if _OUTRA_DIRECAO.search(frase) or not _ATE.search(frase):
            raise ElementoRebaixadoError("termo_ambiguo")
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
    valor = valor_monetario(rascunho["valor"], contexto.texto, rascunho["trecho"])
    if _NEGACAO.search(normalizar(rascunho["trecho"])):
        raise ElementoRebaixadoError("termo_ambiguo")
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
        "admitido_ate só vale para 'até'; 'a partir de', 'depois de' e 'antes de' são generico. "
        "Bônus em percentual, negado ('não', 'exceto', 'nunca'), sem alvo identificável, por "
        "faixa de venda ou com outro critério de filtro (loja, marca) é generico."
    ),
    converter=converter,
)
