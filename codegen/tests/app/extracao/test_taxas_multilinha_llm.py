from decimal import Decimal

import pytest
import simplejson

from app.config import get_settings
from app.extracao.motor import extrair_regra
from app.extracao.reextracao import reextrair_regra
from app.graph.core.llm.registry import get_model, get_model_metadata
from app.representacao_regra import RepresentacaoRegra
from tests.app.apoio_provedor_real import executar_com_retentativa_503

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not get_settings().GOOGLE_API_KEY, reason="requer GOOGLE_API_KEY"),
]
PUBLICADAS = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
TAXAS = (
    "Vendedor de loja, cargo 100: 4% sobre suas vendas individuais.",
    "Vendedor de balcão, cargo 200: 2% sobre suas vendas individuais.",
    "Gerente de loja ou gerente de quiosque, cargo 150: 6% sobre\n"
    "  as vendas totais da sua loja no mês.",
)
BONUS = (
    "Para cada vendedor do cargo 100 abrangido pela regra, acrescente\n"
    "um bônus fixo de R$ 400,00 quando suas vendas individuais no mês\n"
    "forem iguais ou superiores a R$ 45.000,00. Pague esse bônus\n"
    "uma única vez por colaborador em cada competência."
)
PARAMETROS = {
    "competencias": ["2025-08", "2025-10", "2025-12"],
    "meta_venda": Decimal("15000000"),
    "orcamento": Decimal("900000"),
}
PARES = {"100": Decimal("0.04"), "200": Decimal("0.02"), "150": Decimal("0.06")}


@pytest.fixture(autouse=True)
def cliente_do_provedor_no_loop_atual() -> None:
    get_model.cache_clear()


@pytest.mark.parametrize("quebra", ["\n", "\r\n"])
async def test_modelo_real_extrai_taxas_e_bonus_sem_perder_linhas(quebra: str) -> None:
    texto = (
        "Simule agosto, outubro e dezembro de 2025.\n\n"
        "A meta de vendas total é de R$ 15.000.000,00 e o orçamento\n"
        "total de comissões para o mesmo período é de R$ 900.000,00.\n\n"
        "A regra vale somente nas lojas 13 e 58, nas marcas PRETO\n"
        "e AZUL, e abrange os cargos 100, 150 e 200.\n\nAs taxas são:\n- "
        + "\n- ".join(TAXAS)
        + "\n\n"
        + BONUS
        + "\n\nOs demais cargos e os registros fora das lojas e marcas\n"
        "indicadas devem conservar as comissões do baseline.\n"
        "Não há vigência adicional: use as competências da simulação."
    ).replace("\n", quebra)

    resultado = await executar_com_retentativa_503(
        lambda: extrair_regra(
            texto,
            PUBLICADAS,
            modelo=get_model("extraction"),
            metadados_modelo=get_model_metadata("extraction"),
        )
    )

    regra = resultado.representacao.para_contrato()
    assert {par["cargo"]: par["percentual"] for par in regra["nucleo"]["taxas_por_cargo"]} == PARES
    assert "percentual" not in regra["nucleo"]
    assert resultado.parametros == PARAMETROS
    assert any(
        elemento["construto"] == "generico"
        and " ".join(elemento["descricao"].split()) == " ".join(BONUS.split())
        for elemento in regra["especificacoes"]
    ), simplejson.dumps(
        {
            "regra_sintetica": regra,
            "diagnosticos": [diagnostico.motivo for diagnostico in resultado.rebaixamentos],
            "resposta_sintetica": resultado.chamada.resposta,
        },
        ensure_ascii=False,
        use_decimal=True,
    )
    assert all(elemento["construto"] != "bonus_fixo" for elemento in regra["especificacoes"])
    assert all(
        rebaixamento.motivo != "valor_sem_lastro" for rebaixamento in resultado.rebaixamentos
    )


@pytest.mark.parametrize("quebra", ["\n", "\r\n"])
async def test_modelo_real_corrige_taxas_sem_apagar_bonus_ou_duplicar_comissao(quebra: str) -> None:
    bonus = {"ref": "elem.1", "construto": "generico", "descricao": BONUS}
    regra = RepresentacaoRegra.model_validate(
        {
            "nucleo": {"loja": ["13", "58"], "marca": ["10", "30"], "cargo": ["100", "150", "200"]},
            "especificacoes": [
                bonus,
                *[
                    {"ref": f"elem.{indice}", "construto": "generico", "descricao": taxa}
                    for indice, taxa in enumerate(TAXAS[:2], 2)
                ],
            ],
        }
    )
    texto = ("As taxas são:\n- " + "\n- ".join(TAXAS)).replace("\n", quebra)

    resultado = await executar_com_retentativa_503(
        lambda: reextrair_regra(
            regra,
            PARAMETROS,
            [{"elementos": ["nucleo.percentual"], "motivo": "percentual ausente"}],
            texto,
            PUBLICADAS,
            modelo=get_model("extraction"),
            metadados_modelo=get_model_metadata("extraction"),
        )
    )

    corrigida = resultado.representacao.para_contrato()
    assert {
        par["cargo"]: par["percentual"] for par in corrigida["nucleo"]["taxas_por_cargo"]
    } == PARES, {
        "resposta_sintetica": simplejson.loads(resultado.chamada.resposta),
        "diagnosticos": [diagnostico.motivo for diagnostico in resultado.rebaixamentos],
    }
    assert "percentual" not in corrigida["nucleo"]
    assert corrigida["especificacoes"] == [bonus]
    assert resultado.parametros == PARAMETROS
    assert resultado.rebaixamentos == []
