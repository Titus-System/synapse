"""Teste opcional com LLM real para a reextração da T-220."""

from decimal import Decimal

import pytest

from app.representacao_regra import RepresentacaoRegra


@pytest.mark.llm
async def test_modelo_real_reextrai_percentual_sem_perder_regra() -> None:
    pytest.importorskip("google.genai", reason="cliente google.genai não instalado")
    from app.config import get_settings
    from app.extracao.reextracao import reextrair_regra
    from app.graph.core.llm.registry import get_model, get_model_metadata
    from tests.app.apoio_provedor_real import executar_com_retentativa_503

    if not get_settings().GOOGLE_API_KEY:
        pytest.skip("requer GOOGLE_API_KEY")

    get_model.cache_clear()
    regra = RepresentacaoRegra.model_validate(
        {
            "nucleo": {"percentual": Decimal("0.025"), "loja": ["13"]},
            "especificacoes": [],
        }
    )
    resultado = await executar_com_retentativa_503(
        lambda: reextrair_regra(
            regra,
            {"orcamento": Decimal("500000"), "competencias": ["2025-10"]},
            [{"elementos": ["nucleo.percentual"], "motivo": "percentual precisa corrigir"}],
            "O percentual da comissão passa para 3%.",
            ["2025-09", "2025-10", "2025-11"],
            modelo=get_model("extraction"),
            metadados_modelo=get_model_metadata("extraction"),
        )
    )

    assert resultado.representacao.para_contrato() == {
        "nucleo": {"percentual": Decimal("0.03"), "loja": ["13"]},
        "especificacoes": [],
    }
    assert resultado.parametros == {
        "orcamento": Decimal("500000"),
        "competencias": ["2025-10"],
    }
