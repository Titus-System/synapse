from typing import Any

from app.extracao.construto import Construto, ContextoExtracao
from app.extracao.efeito import SCHEMA_EFEITO, normalizar_efeito
from app.extracao.lastro import resolver_datas
from app.extracao.modelos import ElementoRebaixadoError
from app.tipos_estado import ValorRegra

_DATA = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}


def converter(rascunho: dict[str, Any], contexto: ContextoExtracao) -> dict[str, ValorRegra]:
    efeito = normalizar_efeito(rascunho["efeito"], rascunho["trecho"])
    datas = resolver_datas(rascunho["trecho"], contexto.competencias)
    if datas is None:
        raise ElementoRebaixadoError("periodo_nao_resolvido")
    # Um dia só repete a data. A janela invertida sai como dita; quem a aponta é a validação.
    if len(datas) == 1:
        datas = [datas[0], datas[0]]
    if datas != [rascunho["data_inicial"], rascunho["data_final"]]:
        raise ElementoRebaixadoError("valor_sem_lastro")
    return {"data_inicial": datas[0], "data_final": datas[1], "efeito": efeito}


JANELA_DATAS = Construto(
    propriedades={"data_inicial": _DATA, "data_final": _DATA, "efeito": SCHEMA_EFEITO},
    obrigatorios=("data_inicial", "data_final", "efeito"),
    instrucoes=(
        "janela_datas: efeito sobre as vendas feitas dentro de um intervalo de datas. "
        "data_inicial e data_final em AAAA-MM-DD, só se o texto traz as datas (um dia só repete "
        "a data). O trecho cobre as datas e o efeito e não traz outras datas. Na descricao, "
        "mantenha as datas como o texto as escreve (24/11). "
        "efeito: tipo acrescimo_pct ('+1% no percentual', valor 0.01), substituicao_pct ('o "
        "percentual passa a ser 3%') ou bonus_fixo (valor em reais), com valor como {valor, "
        "trecho}. Evento sem datas ('Black Friday'), acréscimo na base de cálculo ou efeito não "
        "identificável é generico."
    ),
    converter=converter,
)
