from copy import deepcopy
from decimal import Decimal

import pytest

from app.nos.codigos_conflito import CodigoConflito
from app.nos.validacao_dominio import verificar

REGRA = {
    "nucleo": {"loja": [], "marca": [], "cargo": [], "percentual": Decimal("0.03")},
    "especificacoes": [],
}
PARAMETROS = {"orcamento": 0, "meta_venda": 12000000}


@pytest.mark.parametrize("campo", ["loja", "marca", "cargo"])
def test_ausencia_de_escopo_e_pendencia_e_lista_vazia_e_declaracao_universal(campo: str) -> None:
    regra = deepcopy(REGRA)
    del regra["nucleo"][campo]
    pendente = verificar(regra, PARAMETROS)
    assert [(c.codigo, c.elementos) for c in pendente.conflitos] == [
        (CodigoConflito.ESCOPO_AUSENTE, (f"nucleo.{campo}",)),
    ]
    assert verificar(REGRA, PARAMETROS).liberado


@pytest.mark.parametrize(
    ("campo", "codigo"),
    [
        ("meta_venda", CodigoConflito.META_VENDA_AUSENTE),
        ("orcamento", CodigoConflito.ORCAMENTO_AUSENTE),
    ],
)
def test_parametro_financeiro_ausente_bloqueia_nova_simulacao(
    campo: str, codigo: CodigoConflito
) -> None:
    parametros = {k: v for k, v in PARAMETROS.items() if k != campo}
    resultado = verificar(REGRA, parametros)
    assert [(c.codigo, c.elementos) for c in resultado.conflitos] == [
        (codigo, (f"parametros.{campo}",))
    ]


def test_taxa_por_cargo_e_vigencia_omitida_sao_suficientes_com_escopo_e_parametros() -> None:
    regra = {
        "nucleo": {
            "loja": [],
            "marca": [],
            "cargo": ["100"],
            "taxas_por_cargo": [{"cargo": "100", "percentual": Decimal("0")}],
        },
        "especificacoes": [],
    }
    assert verificar(regra, PARAMETROS).liberado
