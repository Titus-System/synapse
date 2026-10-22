from typing import Any

import pytest

from app.extracao.correcao import aplicar_operacoes_correcao
from app.representacao_regra import RepresentacaoRegra
from tests.app.extracao.test_motor import extrair, modelo_falso


@pytest.mark.parametrize(
    ("campo", "texto"),
    [
        ("loja", "vale para todas as lojas"),
        ("marca", "vale para todas as marcas"),
        ("cargo", "vale para todos os cargos"),
        ("cargo", "vale para todos os funcionários"),
    ],
)
async def test_universal_tem_lastro_e_nao_preenche_dimensoes_omitidas(
    campo: str, texto: str
) -> None:
    resultado = await extrair(
        modelo_falso(
            {
                "nucleo": {campo: {"valor": [], "trecho": texto}},
                "elementos": [],
                "parametros": {},
            }
        ),
        texto,
    )
    assert resultado.representacao.para_contrato() == {"nucleo": {campo: []}, "especificacoes": []}
    assert resultado.rebaixamentos == []


@pytest.mark.parametrize(
    ("texto", "trecho"),
    [
        ("vale para a loja 13", "vale para a loja 13"),
        ("não vale para todas as lojas", "todas as lojas"),
        ("vale para todas as marcas", "vale para todas as marcas"),
        ("vale para algumas lojas", "todas as lojas"),
    ],
)
async def test_universal_nao_pode_ser_inventado_ou_trocado_de_dimensao(
    texto: str, trecho: str
) -> None:
    resultado = await extrair(
        modelo_falso(
            {
                "nucleo": {"loja": {"valor": [], "trecho": trecho}},
                "elementos": [],
                "parametros": {},
            }
        ),
        texto,
    )
    assert resultado.representacao.para_contrato()["nucleo"] == {}
    assert len(resultado.rebaixamentos) == 1


@pytest.mark.parametrize("valor", [[], {"valor": [], "trecho": "todas as lojas"}])
def test_correcao_universal_preserva_os_outros_campos(valor: Any) -> None:
    regra = RepresentacaoRegra.model_validate(
        {"nucleo": {"loja": ["13"], "marca": ["10"]}, "especificacoes": []}
    )
    corrigida, parametros, diagnosticos = aplicar_operacoes_correcao(
        regra,
        {"meta_venda": 1000},
        {
            "operacoes": [
                {
                    "tipo": "definir_nucleo",
                    "campo": "loja",
                    "valor": valor,
                    "trecho": "todas as lojas",
                }
            ],
        },
        ["2025-11"],
        texto_correcao="vale para todas as lojas",
    )
    assert corrigida.para_contrato()["nucleo"] == {"loja": [], "marca": ["10"]}
    assert parametros == {"meta_venda": 1000}
    assert diagnosticos == []


def test_correcao_vazia_sem_declaracao_universal_nao_apaga_escopo() -> None:
    regra = RepresentacaoRegra.model_validate({"nucleo": {"loja": ["13"]}, "especificacoes": []})
    corrigida, _, diagnosticos = aplicar_operacoes_correcao(
        regra,
        {},
        {
            "operacoes": [
                {"tipo": "definir_nucleo", "campo": "loja", "valor": [], "trecho": "mude a taxa"}
            ],
        },
        ["2025-11"],
        texto_correcao="mude a taxa",
    )
    assert corrigida == regra
    assert diagnosticos[0].motivo == "valor_sem_lastro"
