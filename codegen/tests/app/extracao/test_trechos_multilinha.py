from copy import deepcopy
from decimal import Decimal

import pytest
import simplejson

from app.extracao.reextracao import aplicar_resposta_reextracao
from app.representacao_regra import RepresentacaoRegra
from tests.app.extracao.test_motor import extrair, modelo_falso
from tests.app.extracao.test_taxas_por_cargo import par


@pytest.mark.parametrize("separador", ["\n  ", "\r\n", "\t", "\u00a0", "  "])
async def test_taxas_preservam_todos_os_pares_quando_modelo_junta_linhas(separador: str) -> None:
    trecho = "Gerente, cargo 150: 6% sobre as vendas totais da loja."
    taxas = [par("100", "0.04", "cargo 100: 4%"), par("150", "0.06", trecho)]
    texto = "cargo 100: 4%. " + trecho.replace("sobre as", "sobre" + separador + "as")
    rascunho = {"nucleo": {"taxas_por_cargo": taxas}, "parametros": {}, "elementos": []}
    modelo = modelo_falso(rascunho)

    resultado = await extrair(modelo, texto)

    assert resultado.representacao.para_contrato()["nucleo"] == {
        "cargo": ["100", "150"],
        "taxas_por_cargo": [taxa["valor"] for taxa in taxas],
    }
    assert resultado.rebaixamentos == []
    assert simplejson.loads(resultado.chamada.resposta, use_decimal=True) == rascunho
    assert (
        simplejson.loads(resultado.chamada.prompt)["dados_nao_confiaveis_da_regra"]["texto"]
        == texto
    )


@pytest.mark.parametrize(
    "trecho",
    [
        "Gerente, cargo 150: 7% sobre as vendas totais da loja.",
        "Gerente, cargo 150: 6% sobre as vendas individuais da loja.",
        "Gerente, cargo 150: 6% sobre as vendas totais da loja!",
    ],
)
async def test_espacos_nao_autorizam_alterar_taxa_palavra_ou_pontuacao(trecho: str) -> None:
    texto = "Gerente, cargo 150: 6% sobre\n  as vendas totais da loja."
    resultado = await extrair(
        modelo_falso(
            {
                "nucleo": {"taxas_por_cargo": [par("150", "0.06", trecho)]},
                "parametros": {},
                "elementos": [],
            }
        ),
        texto,
    )

    assert "taxas_por_cargo" not in resultado.representacao.para_contrato()["nucleo"]
    assert [diagnostico.motivo for diagnostico in resultado.rebaixamentos] == ["valor_sem_lastro"]


def test_correcao_recupera_espacos_em_operacao_e_valor_sem_mutar_parametros() -> None:
    regra = RepresentacaoRegra.model_validate(
        {"nucleo": {"loja": ["13"], "marca": ["10"], "cargo": ["150"]}, "especificacoes": []}
    )
    original = deepcopy(regra.para_contrato())
    parametros = {"meta_venda": Decimal("15000000"), "orcamento": Decimal("900000")}
    trecho = "cargo 150: 6% sobre as vendas da loja"
    operacoes = {
        "operacoes": [
            {"tipo": "definir_taxa_cargo", "trecho": trecho, "valor": par("150", "0.06", trecho)}
        ]
    }

    corrigida, completos, diagnosticos = aplicar_resposta_reextracao(
        regra,
        parametros,
        simplejson.dumps(operacoes, use_decimal=True),
        "cargo 150: 6% sobre\n  as vendas da loja",
        ["2025-11"],
    )

    assert corrigida.para_contrato() == {
        "nucleo": {
            **original["nucleo"],
            "taxas_por_cargo": [{"cargo": "150", "percentual": Decimal("0.06")}],
        },
        "especificacoes": [],
    }
    assert completos == parametros
    assert diagnosticos == []
    assert regra.para_contrato() == original
