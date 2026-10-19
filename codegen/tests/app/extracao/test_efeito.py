from decimal import Decimal
from typing import Any

import pytest

from app.extracao.efeito import normalizar_efeito, valor_monetario
from app.extracao.modelos import ElementoRebaixadoError


def efeito(tipo: str, valor: str, trecho: str) -> dict[str, Any]:
    return {"tipo": tipo, "valor": {"valor": Decimal(valor), "trecho": trecho}}


@pytest.mark.parametrize(
    ("rascunho", "texto", "esperado"),
    [
        (efeito("acrescimo_pct", "0.01", "+1%"), "acréscimo de +1%", Decimal("0.01")),
        (efeito("acrescimo_pct", "0.005", "0,5 por cento"), "0,5 por cento", Decimal("0.005")),
        (efeito("substituicao_pct", "0.03", "3%"), "passa a ser 3%", Decimal("0.03")),
        (efeito("bonus_fixo", "1000", "R$ 1.000"), "bônus de R$ 1.000", Decimal("1000")),
        (efeito("bonus_fixo", "1000", "mil reais"), "bônus de mil reais", Decimal("1000")),
    ],
)
def test_normaliza_percentual_em_fracao_e_bonus_em_reais(
    rascunho: dict[str, Any], texto: str, esperado: Decimal
) -> None:
    assert normalizar_efeito(rascunho, texto) == {"tipo": rascunho["tipo"], "valor": esperado}


@pytest.mark.parametrize(
    ("rascunho", "motivo"),
    [
        (efeito("acrescimo_pct", "0.02", "+1%"), "valor_sem_lastro"),
        (efeito("substituicao_pct", "3", "R$ 3"), "valor_sem_lastro"),
        (efeito("bonus_fixo", "1", "1%"), "campo_obrigatorio_ausente"),
        (efeito("bonus_fixo", "500", "R$ 1.000"), "valor_sem_lastro"),
    ],
)
def test_recusa_valor_sem_lastro_ou_de_outra_grandeza_sem_reter_o_conteudo(
    rascunho: dict[str, Any], motivo: str
) -> None:
    with pytest.raises(ElementoRebaixadoError) as erro:
        normalizar_efeito(rascunho, "+1% 1% R$ 3 R$ 1.000")

    assert erro.value.motivo == motivo
    assert str(erro.value) == motivo


def test_valor_monetario_exige_trecho_literal_do_texto() -> None:
    with pytest.raises(ElementoRebaixadoError):
        valor_monetario({"valor": Decimal("500"), "trecho": "R$ 500"}, "bônus de R$ 600")
