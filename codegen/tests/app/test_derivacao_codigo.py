"""O código da alternativa de taxa derivado do código já simulado da versão de origem."""

from decimal import Decimal
from typing import Any

from app.derivacao_codigo import pares_de_taxa, trocar_taxas

ORIGEM: dict[str, Any] = {
    "nucleo": {
        "loja": ["13", "58"],
        "cargo": ["100", "150", "200"],
        "taxas_por_cargo": [
            {"cargo": "100", "percentual": Decimal("0.03")},
            {"cargo": "200", "percentual": Decimal("0.025")},
            {"cargo": "150", "percentual": Decimal("0.05")},
        ],
    },
    "especificacoes": [{"ref": "elem.1", "construto": "generico", "descricao": "bônus de R$ 350"}],
}


def _alternativa(**taxas: Decimal) -> dict[str, Any]:
    return {
        **ORIGEM,
        "nucleo": {
            **ORIGEM["nucleo"],
            "taxas_por_cargo": [
                {
                    "cargo": par["cargo"],
                    "percentual": taxas.get(f"c{par['cargo']}", par["percentual"]),
                }
                for par in ORIGEM["nucleo"]["taxas_por_cargo"]
            ],
        },
    }


ALTERNATIVA = _alternativa(c100=Decimal("0.0204"), c200=Decimal("0.0170"), c150=Decimal("0.0340"))

# O formato do código que passou no job da demonstração: as taxas num dicionário, o bônus e o
# limiar em reais, e um comentário com acento na mesma linha de uma constante trocada.
FONTE = """import pandas as pd

def aplicar_regra(bases, apuracao_base, competencias):
    simulada = apuracao_base.copy()
    taxas = {100: 0.03, 200: 0.025, 150: 0.05}  # gerente é sobre a loja
    for cargo, taxa in taxas.items():
        simulada.loc[simulada['cod_cargo'] == cargo, 'comissao'] = 1000 * taxa
    bonus = simulada['vlr_venda'] >= 40000
    simulada.loc[bonus, 'comissao'] += 350.0
    return {"apuracao_simulada": simulada, "contribuicoes": [], "elementos_implementados": []}
"""


def test_as_taxas_que_mudaram_formam_os_pares_da_troca() -> None:
    assert pares_de_taxa(ORIGEM, ALTERNATIVA) == {
        Decimal("0.03"): Decimal("0.0204"),
        Decimal("0.025"): Decimal("0.0170"),
        Decimal("0.05"): Decimal("0.0340"),
    }


def test_versao_que_muda_outra_coisa_alem_de_numero_nao_se_deriva() -> None:
    mudou_a_loja = {**ALTERNATIVA, "nucleo": {**ALTERNATIVA["nucleo"], "loja": ["13"]}}
    mudou_o_texto = {
        **ALTERNATIVA,
        "especificacoes": [{"ref": "elem.1", "construto": "generico", "descricao": "outro"}],
    }

    assert pares_de_taxa(ORIGEM, mudou_a_loja) is None
    assert pares_de_taxa(ORIGEM, mudou_o_texto) is None


def test_versao_igual_a_origem_nao_tem_o_que_trocar() -> None:
    assert pares_de_taxa(ORIGEM, ORIGEM) is None


def test_a_mesma_taxa_antiga_virando_duas_novas_nao_se_deriva() -> None:
    origem = _alternativa(c100=Decimal("0.03"), c200=Decimal("0.03"))
    alternativa = _alternativa(c100=Decimal("0.02"), c200=Decimal("0.01"))

    assert pares_de_taxa(origem, alternativa) is None


def test_a_troca_muda_so_as_constantes_das_taxas_e_preserva_o_resto_do_texto() -> None:
    pares = pares_de_taxa(ORIGEM, ALTERNATIVA)
    assert pares is not None

    derivada = trocar_taxas(FONTE, pares)

    assert derivada == FONTE.replace(
        "{100: 0.03, 200: 0.025, 150: 0.05}", "{100: 0.0204, 200: 0.017, 150: 0.034}"
    )


def test_taxa_escrita_em_percentual_ou_como_fracao_nao_se_troca() -> None:
    pares = {Decimal("0.03"): Decimal("0.0204")}

    assert trocar_taxas(FONTE.replace("100: 0.03", "100: 3 / 100"), pares) is None
    assert (
        trocar_taxas(FONTE.replace("100: 0.03", "100: 3.0"), {Decimal("0.03"): Decimal("0.0204")})
        is None
    )


def test_constante_inteira_com_o_valor_da_taxa_nao_e_trocada() -> None:
    fonte = FONTE.replace("1000 * taxa", "1 * taxa")
    pares = {Decimal("1"): Decimal("0.5"), Decimal("0.03"): Decimal("0.0204")}

    assert trocar_taxas(fonte, pares) is None


def test_taxa_inteira_nova_vira_constante_de_ponto_flutuante() -> None:
    derivada = trocar_taxas(FONTE, {Decimal("0.05"): Decimal("1.00")})

    assert derivada is not None
    assert "150: 1.0}" in derivada


def test_codigo_que_nao_compila_ou_sem_aplicar_regra_nao_se_deriva() -> None:
    pares = {Decimal("0.03"): Decimal("0.0204")}

    assert trocar_taxas("def aplicar_regra(:\n    taxa = 0.03\n", pares) is None
    assert (
        trocar_taxas("def outra(bases, apuracao_base, competencias):\n    return 0.03\n", pares)
        is None
    )
