from decimal import Decimal

import pytest

from app.config import get_settings
from app.extracao.motor import extrair_regra
from app.graph.core.llm.registry import get_model, get_model_metadata

# O job nasce com todas as competências publicadas (T-277). Passar só as do período esperado
# esconderia um modelo que as copia para parametros em vez de ler o período no texto.
PUBLICADAS = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]


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
        PUBLICADAS,
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
        PUBLICADAS,
        modelo=get_model("extraction"),
        metadados_modelo=get_model_metadata("extraction"),
    )

    assert resultado.parametros == {
        "orcamento": Decimal("500000"),
        "meta_venda": Decimal("12000000"),
        "competencias": ["2025-09", "2025-10", "2025-11"],
    }


@pytest.mark.llm
@pytest.mark.skipif(not get_settings().GOOGLE_API_KEY, reason="requer GOOGLE_API_KEY")
async def test_modelo_real_le_milhao_e_milhoes_como_valor_inteiro() -> None:
    resultado = await extrair_regra(
        "Comissão de 3% para a marca 10, com orçamento de R$ 1,5 milhão e meta de 12 milhões.",
        PUBLICADAS,
        modelo=get_model("extraction"),
        metadados_modelo=get_model_metadata("extraction"),
    )

    assert resultado.parametros == {
        "orcamento": Decimal("1500000"),
        "meta_venda": Decimal("12000000"),
    }


@pytest.mark.llm
@pytest.mark.skipif(not get_settings().GOOGLE_API_KEY, reason="requer GOOGLE_API_KEY")
async def test_modelo_real_deixa_a_condicao_de_meta_na_regra_e_fora_da_meta_venda() -> None:
    resultado = await extrair_regra(
        "Comissão de 2% para a loja 13 e bônus de R$ 300 para quem bater a meta de vendas do mês.",
        PUBLICADAS,
        modelo=get_model("extraction"),
        metadados_modelo=get_model_metadata("extraction"),
    )

    assert "meta_venda" not in resultado.parametros
    assert len(resultado.representacao.para_contrato()["especificacoes"]) == 1


@pytest.mark.llm
@pytest.mark.skipif(not get_settings().GOOGLE_API_KEY, reason="requer GOOGLE_API_KEY")
async def test_modelo_real_nao_preenche_parametro_que_o_texto_nao_diz() -> None:
    resultado = await extrair_regra(
        "Comissão de 2,5% para a loja 13.",
        PUBLICADAS,
        modelo=get_model("extraction"),
        metadados_modelo=get_model_metadata("extraction"),
    )

    assert resultado.parametros == {}


@pytest.mark.llm
@pytest.mark.skipif(not get_settings().GOOGLE_API_KEY, reason="requer GOOGLE_API_KEY")
async def test_modelo_real_le_vigencia_da_comissao_sem_fazer_dela_o_periodo() -> None:
    resultado = await extrair_regra(
        "Comissão de 3% em novembro de 2025 para a loja 13.",
        PUBLICADAS,
        modelo=get_model("extraction"),
        metadados_modelo=get_model_metadata("extraction"),
    )

    assert resultado.parametros == {}
    assert resultado.representacao.para_contrato()["nucleo"]["vigencia"] == {
        "inicio": "2025-11",
        "fim": "2025-11",
    }


@pytest.mark.llm
@pytest.mark.skipif(not get_settings().GOOGLE_API_KEY, reason="requer GOOGLE_API_KEY")
@pytest.mark.parametrize(
    ("periodo", "competencias"),
    [
        # Um período que não é o publicado inteiro: copiar as publicadas não passa.
        ("setembro a dezembro de 2025", ["2025-09", "2025-10", "2025-11", "2025-12"]),
        # O caso em que o modelo, gerando os elementos antes dos parâmetros, fazia do pedido de
        # simular um elemento e deixava parametros vazio.
        ("agosto a dezembro de 2025", PUBLICADAS),
    ],
)
async def test_modelo_real_le_o_periodo_mandado_simular_sem_fazer_dele_elemento(
    periodo: str, competencias: list[str]
) -> None:
    resultado = await extrair_regra(
        f"Comissão de 3% em novembro de 2025 para a loja 13; simular de {periodo}.",
        PUBLICADAS,
        modelo=get_model("extraction"),
        metadados_modelo=get_model_metadata("extraction"),
    )

    assert resultado.parametros == {"competencias": competencias}
    regra = resultado.representacao.para_contrato()
    assert regra["nucleo"]["vigencia"] == {"inicio": "2025-11", "fim": "2025-11"}
    assert regra["especificacoes"] == []
