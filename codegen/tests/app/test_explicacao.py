from decimal import Decimal

import pytest

from app.explicacao import (
    NumerosCitaveis,
    formatar_percentual,
    formatar_reais,
    montar_numeros_citaveis,
    narrativa_confere,
)

TOTAIS = {
    "baseline": Decimal("480312"),
    "simulado": Decimal("492100"),
    "diferenca_abs": Decimal("11788"),
    "diferenca_pct": Decimal("0.0245"),
    "orcamento": Decimal("485000"),
}
DECOMPOSICAO = {
    "elemento": {"nucleo.percentual": Decimal("8200"), "elem.1": Decimal("3588")},
    "loja": {"13": Decimal("7100"), "58": Decimal("4688")},
    "marca": {"10": Decimal("11788")},
    "cargo": {"100": Decimal("9200"), "150": Decimal("2588")},
    "competencia": {"2025-08": Decimal("0"), "2025-11": Decimal("11788")},
    "loja_absoluto": {"13": Decimal("274850"), "58": Decimal("217250")},
}
REGRA = {
    "nucleo": {
        "vigencia": {"inicio": "2025-11", "fim": "2025-11"},
        "loja": ["13"],
        "marca": ["10"],
        "cargo": ["100"],
        "percentual": Decimal("0.025"),
        "descricao": "texto livre com 777 que não autoriza número",
    },
    "especificacoes": [
        {
            "ref": "elem.1",
            "construto": "faixa_valor",
            "limite_inferior": 40000,
            "limite_superior": 50000,
            "efeito": {"tipo": "bonus_fixo", "valor": 3500},
        },
        {
            "ref": "elem.2",
            "construto": "janela_datas",
            "data_inicial": "2025-11-24",
            "data_final": "2025-11-30",
            "efeito": {"tipo": "acrescimo_pct", "valor": Decimal("0.01")},
        },
    ],
}


@pytest.fixture
def citaveis() -> NumerosCitaveis:
    return montar_numeros_citaveis(
        totais=TOTAIS,
        decomposicao=DECOMPOSICAO,
        regra=REGRA,
        competencias=["2025-11"],
        meta_venda=Decimal("1000000"),
    )


def test_formata_reais_e_percentual_como_no_brasil() -> None:
    assert formatar_reais(Decimal("492100")) == "R$ 492.100,00"
    assert formatar_reais(Decimal("-1234.567")) == "-R$ 1.234,57"
    assert formatar_percentual(Decimal("0.0245")) == "2,45%"
    assert formatar_percentual(Decimal("0.025")) == "2,50%"


def test_narrativa_com_simulado_diferenca_loja_e_competencia_confere(
    citaveis: NumerosCitaveis,
) -> None:
    texto = (
        "A regra simulou R$ 492.100,00 em novembro de 2025, uma diferença de 2,45% sobre o "
        "baseline. A loja 13 respondeu por R$ 7.100,00 dessa diferença."
    )

    assert narrativa_confere(texto, citaveis)


def test_narrativa_com_participacao_calculada_da_loja_e_reprovada(
    citaveis: NumerosCitaveis,
) -> None:
    texto = "A loja 13 respondeu por 60,2% da diferença."

    assert not narrativa_confere(texto, citaveis)


@pytest.mark.parametrize(
    "texto",
    [
        "O custo foi R$ 492.101,00.",
        "O custo foi de sessenta mil reais.",
        "Houve 3,5% de diferença.",
        "A loja 14 puxou o efeito.",
        "O número 777 apareceu.",
        "7. Primeiro item.",
    ],
)
def test_qualquer_numero_fora_da_lista_reprova_a_narrativa(
    citaveis: NumerosCitaveis, texto: str
) -> None:
    assert not narrativa_confere(texto, citaveis)


def test_percentual_e_comparado_como_fracao_e_nao_como_valor(citaveis: NumerosCitaveis) -> None:
    # 2.450% teria o valor 24,5, que nenhum dos números apurados tem.
    assert narrativa_confere("diferença de 2,45%", citaveis)
    assert not narrativa_confere("diferença de 245%", citaveis)
    # 13% não é a loja 13: o código só vale como número simples.
    assert not narrativa_confere("a loja respondeu por 13%", citaveis)


def test_os_numeros_da_regra_e_do_periodo_podem_ser_citados(citaveis: NumerosCitaveis) -> None:
    texto = (
        "A regra paga 2,50% nas lojas 13, marca 10 e cargo 100, mais bônus de R$ 3.500,00 acima "
        "de R$ 40.000,00, com acréscimo de 1,00% entre 24/11/2025 e 30/11/2025, para a meta de "
        "R$ 1.000.000,00 e o orçamento de R$ 485.000,00."
    )

    assert narrativa_confere(texto, citaveis)


def test_a_competencia_pode_ser_citada_por_ano_e_mes(citaveis: NumerosCitaveis) -> None:
    assert narrativa_confere("competência 2025-11, ou 11/2025", citaveis)


def test_numero_em_texto_livre_da_regra_nao_autoriza_citacao(citaveis: NumerosCitaveis) -> None:
    assert not any("777" in linha for linha in citaveis.linhas)


def test_artigos_nao_reprovam_a_narrativa(citaveis: NumerosCitaveis) -> None:
    assert narrativa_confere("Uma loja concentrou um aumento relevante.", citaveis)


def test_a_lista_nao_traz_a_participacao_de_nenhuma_loja(citaveis: NumerosCitaveis) -> None:
    assert not any("%" in linha for linha in citaveis.linhas if "loja" in linha.lower())
