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
        (
            efeito("acrescimo_pct", "0.025", "dois e meio por cento"),
            "dois e meio por cento",
            Decimal("0.025"),
        ),
        (
            efeito("acrescimo_pct", "0.01", "De 1/11 a 30/11 haverá +1%"),
            "De 1/11 a 30/11 haverá +1%",
            Decimal("0.01"),
        ),
        (efeito("bonus_fixo", "1000", "R$ 1.000"), "bônus de R$ 1.000", Decimal("1000")),
        (efeito("bonus_fixo", "1000", "mil reais"), "bônus de mil reais", Decimal("1000")),
    ],
)
def test_normaliza_percentual_em_fracao_e_bonus_em_reais(
    rascunho: dict[str, Any], texto: str, esperado: Decimal
) -> None:
    assert normalizar_efeito(rascunho, texto) == {"tipo": rascunho["tipo"], "valor": esperado}


@pytest.mark.parametrize("tipo", ["acrescimo_pct", "substituicao_pct"])
@pytest.mark.parametrize(
    ("trecho", "valor"),
    [
        ("acréscimo percentual de 0,01 em fração", "0.01"),
        ("0,01 (fração) no percentual", "0.01"),
        ("percentual em fração de 0.025", "0.025"),
        ("0,01 em fração", "0.01"),
        ("fração: -0,01", "-0.01"),
        ("0,01 como fração do percentual", "0.01"),
        ("percentual em fração decimal de 0,01", "0.01"),
        ("R$ 200 e fração de 0,01", "0.01"),
        ("fração de 0,01 e bônus de R$ 200", "0.01"),
    ],
)
def test_aceita_fracao_explicita_sem_dividir_novamente(tipo: str, trecho: str, valor: str) -> None:
    assert normalizar_efeito(efeito(tipo, valor, trecho), trecho) == {
        "tipo": tipo,
        "valor": Decimal(valor),
    }


@pytest.mark.parametrize("tipo", ["acrescimo_pct", "substituicao_pct"])
@pytest.mark.parametrize(
    ("trecho", "valor"),
    [
        ("dia 1/11 e percentual de 0,01 em fração", "1"),
        ("R$ 200 e percentual de 0,01 em fração", "200"),
        ("percentual em fração de 1/11", "1"),
        ("R$ 1 em fração no percentual", "1"),
        ("percentual em fração de 0.025", "25"),
    ],
)
def test_fracao_explicita_nao_valida_data_nem_valor_monetario(
    tipo: str, trecho: str, valor: str
) -> None:
    with pytest.raises(ElementoRebaixadoError) as erro:
        normalizar_efeito(efeito(tipo, valor, trecho), trecho)

    assert erro.value.motivo == "valor_sem_lastro"


@pytest.mark.parametrize("tipo", ["acrescimo_pct", "substituicao_pct"])
@pytest.mark.parametrize(
    "trecho",
    ["uma fração da comissão", "uma fração do percentual", "uma fração por cento"],
)
def test_fracao_sem_proporcao_nao_aceita_valor_inventado(tipo: str, trecho: str) -> None:
    with pytest.raises(ElementoRebaixadoError) as erro:
        normalizar_efeito(efeito(tipo, "0.37", trecho), trecho)

    assert erro.value.motivo == "valor_sem_lastro"


@pytest.mark.parametrize("tipo", ["acrescimo_pct", "substituicao_pct"])
@pytest.mark.parametrize(
    ("texto", "trecho", "valor"),
    [
        ("fração de 0,01 reais", "fração de 0,01 reais", "0.01"),
        ("fração de 500 reais", "fração de 500 reais", "500"),
        ("fração de 1 real", "fração de 1 real", "1"),
        ("0,01 em fração (R$)", "0,01 em fração (R$)", "0.01"),
        ("fração de 0,01 reais", "fração de 0,01", "0.01"),
        ("R$ 0,01 em fração", "0,01 em fração", "0.01"),
        ("fração de 0,01 centavos", "fração de 0,01 centavos", "0.01"),
    ],
)
def test_fracao_monetaria_nao_vira_percentual(
    tipo: str, texto: str, trecho: str, valor: str
) -> None:
    with pytest.raises(ElementoRebaixadoError) as erro:
        normalizar_efeito(efeito(tipo, valor, trecho), texto)

    assert erro.value.motivo == "valor_sem_lastro"


@pytest.mark.parametrize(
    ("rascunho", "motivo"),
    [
        (efeito("acrescimo_pct", "0.02", "+1%"), "valor_sem_lastro"),
        (efeito("substituicao_pct", "3", "R$ 3"), "valor_sem_lastro"),
        (efeito("bonus_fixo", "1", "1%"), "campo_obrigatorio_ausente"),
        (efeito("bonus_fixo", "500", "R$ 1.000"), "valor_sem_lastro"),
        (
            efeito("acrescimo_pct", "1", "De 1/11 a 30/11 haverá +1%"),
            "valor_sem_lastro",
        ),
        (
            efeito("substituicao_pct", "200", "R$ 200 e percentual de 3%"),
            "valor_sem_lastro",
        ),
    ],
)
def test_recusa_valor_sem_lastro_ou_de_outra_grandeza_sem_reter_o_conteudo(
    rascunho: dict[str, Any], motivo: str
) -> None:
    with pytest.raises(ElementoRebaixadoError) as erro:
        normalizar_efeito(
            rascunho,
            "+1% 1% R$ 3 R$ 1.000. De 1/11 a 30/11 haverá +1%. R$ 200 e percentual de 3%",
        )

    assert erro.value.motivo == motivo
    assert str(erro.value) == motivo


def test_valor_monetario_exige_trecho_literal_do_texto() -> None:
    with pytest.raises(ElementoRebaixadoError):
        valor_monetario({"valor": Decimal("500"), "trecho": "R$ 500"}, "bônus de R$ 600")
