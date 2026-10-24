from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest

from app.extracao.correcao import aplicar_operacoes_correcao
from app.nos.validacao_dominio import verificar
from app.representacao_regra import RepresentacaoRegra
from tests.app.extracao.test_motor import extrair, modelo_falso


def par(cargo: str, percentual: str, trecho: str) -> dict[str, Any]:
    return {"valor": {"cargo": cargo, "percentual": Decimal(percentual)}, "trecho": trecho}


async def test_extrai_todos_os_pares_sem_inventar_taxa_uniforme() -> None:
    taxas = [par("100", "0.03", "cargo 100 recebe 3%"), par("150", "0.05", "gerente recebe 5%")]
    resultado = await extrair(
        modelo_falso({"nucleo": {"taxas_por_cargo": taxas}, "elementos": [], "parametros": {}}),
        "O cargo 100 recebe 3% e o gerente recebe 5%.",
    )
    nucleo = resultado.representacao.para_contrato()["nucleo"]
    assert nucleo == {
        "cargo": ["100", "150"],
        "taxas_por_cargo": [taxa["valor"] for taxa in taxas],
    }
    assert resultado.rebaixamentos == []
    assert verificar(resultado.representacao.para_contrato()).liberado


@pytest.mark.parametrize(
    "segundo",
    [
        par("150", "0.09", "cargo 150 recebe 5%"),
        par("200", "0.05", "cargo 150 recebe 5%"),
        par("150", "0.03", "cargo 100 recebe 3% e cargo 150 recebe 5%"),
    ],
)
async def test_par_sem_lastro_ou_associacao_ambigua_nao_vira_proposta_parcial(
    segundo: dict[str, Any],
) -> None:
    taxas = [par("100", "0.03", "cargo 100 recebe 3%"), segundo]
    resultado = await extrair(
        modelo_falso({"nucleo": {"taxas_por_cargo": taxas}, "elementos": [], "parametros": {}}),
        "cargo 100 recebe 3% e cargo 150 recebe 5%",
    )
    regra = resultado.representacao.para_contrato()
    assert "taxas_por_cargo" not in regra["nucleo"]  # type: ignore[operator]
    assert regra["especificacoes"] == []
    assert [r.ref for r in resultado.rebaixamentos] == ["nucleo.taxas_por_cargo"]
    assert not verificar(regra).liberado


@pytest.mark.parametrize("percentual", ["0", "-0.01"])
async def test_preserva_zero_e_negativo_para_validacao_do_dominio(percentual: str) -> None:
    texto = "cargo 100 recebe 0%" if percentual == "0" else "cargo 100 recebe -1%"
    taxa = par("100", percentual, texto)
    resultado = await extrair(
        modelo_falso({"nucleo": {"taxas_por_cargo": [taxa]}, "elementos": [], "parametros": {}}),
        texto,
    )
    assert verificar(resultado.representacao.para_contrato()).liberado == (percentual == "0")


@pytest.fixture
def regra() -> RepresentacaoRegra:
    return RepresentacaoRegra.model_validate(
        {
            "nucleo": {
                "loja": [],
                "marca": ["10"],
                "cargo": ["100", "150"],
                "taxas_por_cargo": [
                    {"cargo": "100", "percentual": Decimal("0.03")},
                    {"cargo": "150", "percentual": Decimal("0.05")},
                ],
            },
            "especificacoes": [
                {"ref": "elem.1", "construto": "generico", "descricao": "condição original"}
            ],
        }
    )


def test_correcao_altera_so_o_par_citado(regra: RepresentacaoRegra) -> None:
    original = deepcopy(regra.para_contrato())
    texto = "cargo 100 recebe 4%"
    corrigida, parametros, diagnosticos = aplicar_operacoes_correcao(
        regra,
        {"orcamento": 1000},
        {
            "operacoes": [
                {"tipo": "definir_taxa_cargo", "valor": par("100", "0.04", texto), "trecho": texto}
            ]
        },
        ["2025-11"],
        texto_correcao=texto,
    )
    esperado = deepcopy(original)
    esperado["nucleo"]["taxas_por_cargo"][0]["percentual"] = Decimal("0.04")  # type: ignore[index]
    assert corrigida.para_contrato() == esperado
    assert regra.para_contrato() == original
    assert parametros == {"orcamento": 1000}
    assert diagnosticos == []


def test_remover_ultimo_par_reabre_pendencia(regra: RepresentacaoRegra) -> None:
    texto = "remova as taxas dos cargos 100 e 150"
    operacoes = [
        {"tipo": "remover_taxa_cargo", "cargo": {"valor": cargo, "trecho": texto}, "trecho": texto}
        for cargo in ("100", "150")
    ]
    corrigida, _, diagnosticos = aplicar_operacoes_correcao(
        regra,
        {},
        {"operacoes": operacoes},
        ["2025-11"],
        texto_correcao=texto,
    )
    assert diagnosticos == []
    assert not verificar(corrigida.para_contrato()).liberado
    assert "taxas_por_cargo" not in corrigida.para_contrato()["nucleo"]  # type: ignore[operator]


def test_novo_par_amplia_destinatarios_sem_tocar_nas_outras_taxas(
    regra: RepresentacaoRegra,
) -> None:
    texto = "adicione cargo 300 com 2%"
    corrigida, _, diagnosticos = aplicar_operacoes_correcao(
        regra,
        {},
        {
            "operacoes": [
                {"tipo": "definir_taxa_cargo", "valor": par("300", "0.02", texto), "trecho": texto}
            ]
        },
        ["2025-11"],
        texto_correcao=texto,
    )
    nucleo = corrigida.para_contrato()["nucleo"]
    assert isinstance(nucleo, dict)
    assert nucleo["cargo"] == ["100", "150", "300"]
    assert len(nucleo["taxas_por_cargo"]) == 3  # type: ignore[arg-type]
    assert diagnosticos == []
