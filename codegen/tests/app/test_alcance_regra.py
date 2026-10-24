from decimal import Decimal
from itertools import product
from typing import Any

import pytest

from app.alcance_regra import AlcanceDaRegra
from tests.app.test_mensageria import oficial

COMPETENCIAS = ("2025-08", "2025-09", "2025-11")
LOJAS = ("13", "58", "99")
MARCAS = ("10", "20", "30")
CARGOS = ("100", "150", "200", "300")


def _no_alcance_do_comando(alcance: dict[str, Any] | None, competencia: str, linha: dict) -> bool:
    """A leitura que o worker faz do campo `alcance` de `executar-codigo`, pelo contrato."""
    if alcance is None:
        return True
    vigencia = alcance.get("vigencia")
    if vigencia is not None and not vigencia["inicio"] <= competencia <= vigencia["fim"]:
        return False
    for dimensao in ("loja", "marca", "cargo"):
        if dimensao in alcance and linha[f"cod_{dimensao}"] not in alcance[dimensao]:
            return False
    excluidos = alcance.get("excluidos", {})
    return not any(linha[f"cod_{dim}"] in valores for dim, valores in excluidos.items())


REGRAS = {
    "todas_as_lojas_e_marcas": {
        "nucleo": {"loja": [], "marca": [], "cargo": ["100"], "percentual": Decimal("0.03")},
        "especificacoes": [],
    },
    "filtros_e_vigencia": {
        "nucleo": {
            "vigencia": {"inicio": "2025-09", "fim": "2025-11"},
            "loja": ["13", "58"],
            "marca": ["10", "20"],
            "cargo": ["100", "200"],
            "percentual": Decimal("0.03"),
        },
        "especificacoes": [],
    },
    "taxas_por_cargo_sem_uniforme": {
        "nucleo": {
            "loja": ["13"],
            "cargo": ["100", "150", "300"],
            "taxas_por_cargo": [
                {"cargo": "100", "percentual": Decimal("0.03")},
                {"cargo": "150", "percentual": Decimal("0.05")},
            ],
        },
        "especificacoes": [],
    },
    "taxas_por_cargo_sem_filtro": {
        "nucleo": {
            "taxas_por_cargo": [{"cargo": "200", "percentual": Decimal("0.02")}],
        },
        "especificacoes": [],
    },
    "taxa_uniforme_com_excecao": {
        "nucleo": {
            "percentual": Decimal("0.03"),
            "taxas_por_cargo": [{"cargo": "150", "percentual": Decimal("0.05")}],
        },
        "especificacoes": [],
    },
    "exclusao": {
        "nucleo": {"marca": ["10"], "percentual": Decimal("0.03")},
        "especificacoes": [
            {"ref": "elem.1", "construto": "exclusao", "dimensao": "loja", "valores": ["58"]}
        ],
    },
}


@pytest.mark.parametrize("representacao", REGRAS.values(), ids=REGRAS.keys())
def test_alcance_do_comando_decide_cada_linha_como_a_regra(representacao: dict[str, Any]) -> None:
    """O worker só vê o comando: ele tem de chegar à mesma linha alcançada que a sugestão usa."""
    alcance = AlcanceDaRegra.da(representacao)
    comando = alcance.para_comando()

    for competencia, loja, marca, cargo in product(COMPETENCIAS, LOJAS, MARCAS, CARGOS):
        linha = {"cod_loja": loja, "cod_marca": marca, "cod_cargo": cargo}
        assert _no_alcance_do_comando(comando, competencia, linha) == alcance.alcanca(
            competencia, linha
        ), (competencia, linha)


@pytest.mark.parametrize("representacao", REGRAS.values(), ids=REGRAS.keys())
def test_alcance_do_comando_segue_o_contrato(representacao: dict[str, Any]) -> None:
    comando = AlcanceDaRegra.da(representacao).para_comando()
    payload = {
        "job_id": "3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021",
        "codigo_gerado_id": "5d4c3b2a-1f0e-4d9c-8b7a-6e5d4c3b2a19",
        "competencias": list(COMPETENCIAS),
    }
    if comando is not None:
        payload["alcance"] = comando

    oficial("executar-codigo").validate(payload)


def test_regra_que_vale_para_toda_linha_nao_leva_alcance() -> None:
    representacao = {"nucleo": {"percentual": Decimal("0.03")}, "especificacoes": []}

    assert AlcanceDaRegra.da(representacao).para_comando() is None


def test_sem_taxa_uniforme_o_cargo_sem_taxa_propria_fica_fora_do_alcance() -> None:
    comando = AlcanceDaRegra.da(REGRAS["taxas_por_cargo_sem_uniforme"]).para_comando()

    assert comando == {"loja": ["13"], "cargo": ["100", "150"]}


def test_filtro_sem_nenhum_cargo_com_taxa_nao_leva_alcance() -> None:
    """A lista vazia não tem forma no contrato; sem alcance, o worker não reprova nada."""
    representacao = {
        "nucleo": {
            "cargo": ["300"],
            "taxas_por_cargo": [{"cargo": "100", "percentual": Decimal("0.03")}],
        },
        "especificacoes": [],
    }

    assert AlcanceDaRegra.da(representacao).para_comando() is None
