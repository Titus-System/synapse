"""Corpus T-224 executado no aplicador real, independente de provedor LLM."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.extracao.correcao import aplicar_operacoes_correcao
from app.representacao_regra import RepresentacaoRegra

ARQUIVO = Path(__file__).resolve().parents[2] / "fixtures" / "corpus_reextracao.json"
CASOS: list[dict[str, Any]] = json.loads(ARQUIVO.read_text(), parse_float=Decimal)


@pytest.mark.parametrize("caso", CASOS, ids=lambda item: item["id"])
def test_corpus_reextracao_aplica_ou_rebaixa_operacoes(caso: dict[str, Any]) -> None:
    regra = RepresentacaoRegra.model_validate(
        caso.get("regra_atual", {"nucleo": {"percentual": Decimal("0.025")}, "especificacoes": []})
    )
    parametros = {"orcamento": Decimal("500000"), "meta_venda": Decimal("12000000")}

    corrigida, completos, rebaixamentos = aplicar_operacoes_correcao(
        regra,
        parametros,
        {"operacoes": caso["operacoes_falsas"]},
        ["2025-10", "2025-11"],
        texto_correcao=caso["texto"],
    )

    assert corrigida.para_contrato()["nucleo"]["percentual"] == caso["percentual_esperado"]
    assert completos["orcamento"] == caso["orcamento_esperado"]
    assert completos["meta_venda"] == caso["meta_esperada"]
    assert [item.motivo for item in rebaixamentos] == caso["motivos_esperados"]
    assert corrigida.para_contrato()["especificacoes"] == caso.get("especificacoes_esperadas", [])
