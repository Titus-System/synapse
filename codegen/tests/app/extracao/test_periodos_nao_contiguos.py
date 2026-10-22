from decimal import Decimal
from typing import Any

import pytest

from app.extracao.correcao import aplicar_operacoes_correcao
from app.extracao.lastro import conferir_periodo, resolver_periodo
from app.representacao_regra import RepresentacaoRegra
from tests.app.extracao.test_motor import extrair, modelo_falso

PUBLICADAS = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
MESES = ["2025-08", "2025-10", "2025-12"]


@pytest.mark.parametrize(
    "trecho",
    [
        "agosto, outubro e dezembro de 2025",
        "agosto, outubro e dezembro",
        "2025-08, 2025-10 e 2025-12",
        "08/2025, 10/2025 e 12/2025",
    ],
)
def test_enumeracao_preserva_somente_as_competencias_citadas(trecho: str) -> None:
    assert resolver_periodo(trecho, PUBLICADAS) == MESES
    assert conferir_periodo(trecho, trecho, MESES, PUBLICADAS, vigencia=False) == (True, True)
    assert conferir_periodo(trecho, trecho, PUBLICADAS, PUBLICADAS, vigencia=False) == (False, True)


def test_duas_competencias_enumeradas_nao_viram_intervalo() -> None:
    assert resolver_periodo("agosto e dezembro de 2025", PUBLICADAS) == ["2025-08", "2025-12"]
    assert resolver_periodo("entre agosto e dezembro de 2025", PUBLICADAS) == PUBLICADAS
    assert resolver_periodo("de agosto a dezembro de 2025", PUBLICADAS) == PUBLICADAS


def test_enumeracao_sem_ano_ambiguo_permanece_pendente() -> None:
    assert resolver_periodo("agosto, outubro e dezembro", ["2024-12", "2025-01"]) is None


def test_vigencia_nao_pode_transformar_lista_descontinua_em_intervalo() -> None:
    trecho = "agosto, outubro e dezembro de 2025"
    assert conferir_periodo(
        trecho, trecho, {"inicio": "2025-08", "fim": "2025-12"}, PUBLICADAS, vigencia=True
    ) == (False, False)


async def test_extracao_preserva_lista_nao_contigua_sem_pedir_correcao() -> None:
    trecho = "Simule agosto, outubro e dezembro de 2025"
    resultado = await extrair(
        modelo_falso(
            {
                "nucleo": {},
                "elementos": [],
                "parametros": {"competencias": {"valor": MESES, "trecho": trecho}},
            }
        ),
        trecho,
    )
    assert resultado.parametros == {"competencias": MESES}
    assert resultado.rebaixamentos == []


def test_correcao_aplica_lista_nao_contigua_sem_alterar_regra_ou_outros_parametros() -> None:
    regra = RepresentacaoRegra.model_validate(
        {
            "nucleo": {"loja": [], "marca": [], "cargo": [], "percentual": Decimal("0.03")},
            "especificacoes": [],
        }
    )
    trecho = "agosto, outubro e dezembro"
    operacao: dict[str, Any] = {
        "tipo": "definir_parametro",
        "campo": "competencias",
        "valor": {"valor": MESES, "trecho": trecho},
        "trecho": trecho,
    }
    corrigida, parametros, diagnosticos = aplicar_operacoes_correcao(
        regra,
        {"meta_venda": 15000000, "orcamento": 900000},
        {"operacoes": [operacao]},
        PUBLICADAS,
        texto_correcao=trecho,
    )
    assert corrigida == regra
    assert parametros == {"meta_venda": 15000000, "orcamento": 900000, "competencias": MESES}
    assert diagnosticos == []
