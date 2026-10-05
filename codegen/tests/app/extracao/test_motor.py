from decimal import Decimal
from typing import Any

import pytest
import simplejson
from langchain_core.messages import AIMessage

from app.extracao.modelos import ResultadoExtracao
from app.extracao.motor import extrair_regra
from tests.app.graph.conftest import FakeChatModel

METADADOS = {"provedor": "google", "modelo": "fake", "versao": "test"}
TEXTO = "Pague 2,5% na loja 13 e um bônus de R$ 500 em 2025-11."
ELEMENTO = {
    "construto_pretendido": "bonus_fixo",
    "descricao": "um bônus de R$ 500 em 2025-11",
    "trecho": "um bônus de R$ 500 em 2025-11",
}


def modelo_falso(conteudo: object, *, motivo: str | None = "STOP") -> FakeChatModel:
    texto = conteudo if isinstance(conteudo, str) else simplejson.dumps(conteudo, use_decimal=True)
    return FakeChatModel(
        messages=iter([AIMessage(content=texto, response_metadata={"finish_reason": motivo})])
    )


async def extrair(modelo: FakeChatModel, texto: str = TEXTO) -> ResultadoExtracao:
    return await extrair_regra(texto, ["2025-11"], modelo=modelo, metadados_modelo=METADADOS)


@pytest.mark.parametrize(
    "nucleo",
    [
        {},
        {"percentual": Decimal("0.025")},
        {"vigencia": {"inicio": "2025-11", "fim": "2025-11"}},
        {"vigencia": {"inicio": "2025-08", "fim": "2025-12"}},
        {"vigencia": {"inicio": "2025-12", "fim": "2025-08"}, "percentual": Decimal("-0.1")},
        {
            "vigencia": {"inicio": "2025-11", "fim": "2025-11"},
            "loja": ["13"],
            "marca": ["10"],
            "cargo": ["100"],
            "percentual": Decimal("0.025000000000000000001"),
        },
    ],
)
async def test_preserva_nucleo_sem_inventar_campos_ou_corrigir_coerencia(
    nucleo: dict[str, Any],
) -> None:
    resultado = await extrair(modelo_falso({"nucleo": nucleo, "elementos": []}))

    assert resultado.representacao.para_contrato() == {"nucleo": nucleo, "especificacoes": []}
    assert resultado.rebaixamentos == []


async def test_texto_sem_regra_produz_representacao_minima() -> None:
    resultado = await extrair(modelo_falso({"nucleo": {}, "elementos": []}), "Bom dia!")

    assert resultado.representacao.para_contrato() == {"nucleo": {}, "especificacoes": []}


async def test_rebaixa_todos_os_elementos_e_atribui_refs_na_ordem() -> None:
    elementos = [ELEMENTO, {**ELEMENTO, "construto_pretendido": "aniversario_loja"}]

    resultado = await extrair(modelo_falso({"nucleo": {}, "elementos": elementos}))

    assert resultado.representacao.para_contrato()["especificacoes"] == [
        {"ref": f"elem.{i}", "construto": "generico", "descricao": ELEMENTO["descricao"]}
        for i in (1, 2)
    ]
    assert [r.para_contrato() for r in resultado.rebaixamentos] == [
        {
            "ref": f"elem.{i}",
            "construto_pretendido": elemento["construto_pretendido"],
            "motivo": "construto_nao_habilitado",
        }
        for i, elemento in enumerate(elementos, 1)
    ]


@pytest.mark.parametrize("campo", ["construto_pretendido", "descricao", "trecho"])
async def test_rebaixa_campo_obrigatorio_ausente_sem_perder_elemento(campo: str) -> None:
    elemento = {k: v for k, v in ELEMENTO.items() if k != campo}

    resultado = await extrair(modelo_falso({"nucleo": {}, "elementos": [elemento]}))

    assert resultado.representacao.para_contrato()["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": ELEMENTO["descricao"]}
    ]
    assert resultado.rebaixamentos[0].motivo == "campo_obrigatorio_ausente"
    assert resultado.rebaixamentos[0].construto_pretendido == elemento.get("construto_pretendido")


@pytest.mark.parametrize("descricao", [None, 12, [], "", "   "])
async def test_recupera_descricao_inutilizavel_pelo_trecho_literal(descricao: object) -> None:
    elemento = {**ELEMENTO, "descricao": descricao}

    resultado = await extrair(modelo_falso({"nucleo": {}, "elementos": [elemento]}))

    assert resultado.representacao.para_contrato()["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": ELEMENTO["trecho"]}
    ]
    assert resultado.rebaixamentos[0].motivo == "campo_obrigatorio_ausente"


async def test_campo_extra_no_elemento_e_rebaixado_sem_ser_copiado() -> None:
    elemento = {**ELEMENTO, "ref": "elem.99", "campo_desconhecido": "conteudo-teste"}

    resultado = await extrair(modelo_falso({"nucleo": {}, "elementos": [elemento]}))

    assert resultado.representacao.para_contrato()["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": ELEMENTO["descricao"]}
    ]
    assert resultado.rebaixamentos[0].motivo == "construto_nao_habilitado"
