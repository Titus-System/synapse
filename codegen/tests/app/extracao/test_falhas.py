import pytest

from app.extracao.modelos import FalhaExtracaoError
from app.falhas import FalhaDoJobError
from tests.app.extracao.test_motor import ELEMENTO, TEXTO, extrair, modelo_falso


@pytest.mark.parametrize("texto", ["", " ", "\n\t"])
async def test_entrada_vazia_falha_sem_chamar_modelo(texto: str) -> None:
    modelo = modelo_falso({"nucleo": {}, "elementos": []})

    with pytest.raises(FalhaExtracaoError):
        await extrair(modelo, texto)

    assert modelo.seen_messages == []


@pytest.mark.parametrize(
    "conteudo",
    [
        "",
        "   ",
        "segredo fora do JSON",
        "```json\n{}\n```",
        "[]",
        "null",
        '{"nucleo": {}, "elementos": [], "nucleo": {}}',
        {"nucleo": {}, "elementos": [], "campo_desconhecido": "segredo"},
        {"nucleo": {}},
        {"nucleo": [], "elementos": []},
        {"nucleo": {"matricula": "MATRIC-1"}, "elementos": []},
        {"nucleo": {"percentual": True}, "elementos": []},
        {"nucleo": {"percentual": None}, "elementos": []},
        {"nucleo": {"loja": []}, "elementos": []},
        {"nucleo": {"loja": [13]}, "elementos": []},
        {"nucleo": {"vigencia": {"inicio": "2025-13", "fim": "2025-11"}}, "elementos": []},
        {"nucleo": {}, "elementos": ["segredo"]},
        {
            "nucleo": {},
            "elementos": [{"construto_pretendido": "bonus_fixo", "trecho": "inventado"}],
        },
        {"nucleo": {}, "elementos": [], "parametros": {"orcamento": 500000}},
        {"nucleo": {}, "elementos": [], "parametros": {"orcamento": {"valor": 500000}}},
        {
            "nucleo": {},
            "elementos": [],
            "parametros": {"orcamento": {"valor": 500000, "trecho": "x", "extra": 1}},
        },
        {
            "nucleo": {},
            "elementos": [],
            "parametros": {"meta_venda": {"valor": "500000", "trecho": "x"}},
        },
        {
            "nucleo": {},
            "elementos": [],
            "parametros": {"competencias": {"valor": [], "trecho": "x"}},
        },
        {
            "nucleo": {},
            "elementos": [],
            "parametros": {"desconhecido": {"valor": 1, "trecho": "x"}},
        },
    ],
)
async def test_saida_inutilizavel_falha_sem_expor_artefatos(conteudo: object) -> None:
    with pytest.raises(FalhaExtracaoError) as erro:
        await extrair(modelo_falso(conteudo))

    assert isinstance(erro.value, FalhaDoJobError)
    assert erro.value.etapa == "extracao_parametros"
    assert erro.value.__cause__ is None
    assert erro.value.__context__ is None
    assert "segredo" not in str(erro.value)
    assert TEXTO not in str(erro.value)


@pytest.mark.parametrize("motivo", [None, "", "MAX_TOKENS", "SAFETY", "OTHER", "UNKNOWN_9"])
async def test_so_aceita_stop_mesmo_com_json_valido(motivo: str | None) -> None:
    modelo = modelo_falso({"nucleo": {}, "elementos": []}, motivo=motivo)

    with pytest.raises(FalhaExtracaoError):
        await extrair(modelo)


async def test_nao_emite_conteudo_em_logs(caplog: pytest.LogCaptureFixture) -> None:
    await extrair(modelo_falso({"nucleo": {}, "elementos": [ELEMENTO], "parametros": {}}))

    with pytest.raises(FalhaExtracaoError):
        await extrair(modelo_falso("segredo-modelo"))

    assert all(
        TEXTO not in r.getMessage() and "segredo-modelo" not in r.getMessage()
        for r in caplog.records
    )
