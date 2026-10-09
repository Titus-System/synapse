from decimal import Decimal

import pytest

from app.config import get_settings
from app.extracao.motor import extrair_regra
from app.graph.core.llm.registry import get_model, get_model_metadata


@pytest.fixture(autouse=True)
def _cliente_real_no_loop_do_teste() -> None:
    # get_model é cacheado por nome (um cliente por processo); o cliente da chamada real
    # amarra seus sockets ao loop de evento do teste que o criou, e o pytest-asyncio fecha
    # esse loop a cada teste (default_loop_scope=function). Sem isto, o segundo teste com
    # @pytest.mark.llm reusaria um cliente do loop já fechado e falharia na limpeza da
    # conexão com "Event loop is closed", depois de uma chamada ao provedor real bem-sucedida.
    get_model.cache_clear()


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


@pytest.mark.llm
@pytest.mark.skipif(not get_settings().GOOGLE_API_KEY, reason="requer GOOGLE_API_KEY")
async def test_modelo_real_extrai_orcamento_meta_e_periodo_da_simulacao() -> None:
    resultado = await extrair_regra(
        "Comissão de 2,5% para os vendedores da marca 10, com orçamento de R$ 500 mil e "
        "meta de vender R$ 12 milhões entre setembro e novembro de 2025.",
        ["2025-09", "2025-10", "2025-11"],
        modelo=get_model("extraction"),
        metadados_modelo=get_model_metadata("extraction"),
    )

    assert resultado.parametros == {
        "orcamento": Decimal("500000"),
        "meta_venda": Decimal("12000000"),
        "competencias": ["2025-09", "2025-10", "2025-11"],
    }
