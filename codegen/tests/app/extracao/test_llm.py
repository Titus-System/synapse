from decimal import Decimal

import pytest

from app.config import get_settings
from app.extracao.motor import extrair_regra
from app.graph.core.llm.registry import get_model, get_model_metadata


@pytest.mark.llm
@pytest.mark.skipif(not get_settings().GOOGLE_API_KEY, reason="requer GOOGLE_API_KEY")
async def test_modelo_real_extrai_nucleo_sem_duplicar_como_elemento() -> None:
    resultado = await extrair_regra(
        "Comissão de 2,5% de agosto de 2025 a dezembro de 2025, "
        "para a loja de código 13, marca de código 10 e cargo de código 100.",
        ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"],
        modelo=get_model("extraction"),
        metadados_modelo=get_model_metadata("extraction"),
    )

    assert resultado.representacao.para_contrato() == {
        "nucleo": {
            "vigencia": {"inicio": "2025-08", "fim": "2025-12"},
            "loja": ["13"],
            "marca": ["10"],
            "cargo": ["100"],
            "percentual": Decimal("0.025"),
        },
        "especificacoes": [],
    }
    assert resultado.rebaixamentos == []
