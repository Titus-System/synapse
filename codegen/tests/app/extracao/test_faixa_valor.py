from decimal import Decimal
from typing import Any

import pytest

from app.extracao.construtos.faixa_valor import LIMITE_SUPERIOR_ABERTO
from app.extracao.modelos import ResultadoExtracao
from app.extracao.motor import extrair_regra
from tests.app.extracao.test_motor import METADADOS, modelo_falso

TEXTO = (
    "Todas as vendas individuais das marcas 10 e 20 acima de R$ 40 mil fazem jus a um bônus: "
    "40.000 até 50.000, R$ 3.500; 50.001 até 60.000, R$ 4.000; acima de 60.001, R$ 4.500"
)
MAIOR_TOTAL_MENSAL = Decimal("18680000")


def lastro(valor: str, trecho: str) -> dict[str, Any]:
    return {"valor": Decimal(valor), "trecho": trecho}


def faixa(
    trecho: str, inferior: str, superior: str | None, bonus: str, **extra: Any
) -> dict[str, Any]:
    elemento: dict[str, Any] = {
        "construto_pretendido": "faixa_valor",
        "descricao": trecho,
        "trecho": trecho,
        "limite_inferior": lastro(inferior, inferior),
        "faixa_aberta": superior is None,
        "efeito": {"tipo": "bonus_fixo", "valor": lastro(bonus, f"R$ {bonus}")},
        **extra,
    }
    if superior is not None:
        elemento["limite_superior"] = lastro(superior, superior)
    return elemento


FAIXAS = [
    faixa("40000 até 50000, R$ 3500", "40000", "50000", "3500"),
    faixa("50001 até 60000, R$ 4000", "50001", "60000", "4000"),
    faixa("acima de 60001, R$ 4500", "60001", None, "4500"),
]
TEXTO_FAIXAS = "40000 até 50000, R$ 3500; 50001 até 60000, R$ 4000; acima de 60001, R$ 4500"


async def extrair(
    elementos: list[dict[str, Any]], texto: str, nucleo: dict[str, Any] | None = None
) -> ResultadoExtracao:
    modelo = modelo_falso({"nucleo": nucleo or {}, "elementos": elementos, "parametros": {}})
    return await extrair_regra(texto, ["2025-12"], modelo=modelo, metadados_modelo=METADADOS)


def especificacoes(resultado: ResultadoExtracao) -> list[Any]:
    regra: Any = resultado.representacao.para_contrato()
    return list(regra["especificacoes"])


def motivos(resultado: ResultadoExtracao) -> list[str]:
    return [r.motivo for r in resultado.rebaixamentos]


def test_limite_da_faixa_aberta_e_finito_e_maior_que_qualquer_total_do_dataset() -> None:
    assert LIMITE_SUPERIOR_ABERTO.is_finite()
    assert LIMITE_SUPERIOR_ABERTO > MAIOR_TOTAL_MENSAL


async def test_escada_de_bonus_vira_tres_faixas_sequenciais_e_a_marca_fica_no_nucleo() -> None:
    nucleo = {"marca": [{"valor": "10", "trecho": "marcas 10"}, {"valor": "20", "trecho": "20"}]}
    texto = f"Vendas individuais das marcas 10 e 20: {TEXTO_FAIXAS}"

    resultado = await extrair(FAIXAS, texto, nucleo)

    regra: Any = resultado.representacao.para_contrato()
    assert regra["nucleo"] == {"marca": ["10", "20"]}
    assert [
        (e["ref"], e["limite_inferior"], e["limite_superior"], e["efeito"])
        for e in regra["especificacoes"]
    ] == [
        ("elem.1", 40000, 50000, {"tipo": "bonus_fixo", "valor": 3500}),
        ("elem.2", 50001, 60000, {"tipo": "bonus_fixo", "valor": 4000}),
        ("elem.3", 60001, LIMITE_SUPERIOR_ABERTO, {"tipo": "bonus_fixo", "valor": 4500}),
    ]
    assert {e["construto"] for e in regra["especificacoes"]} == {"faixa_valor"}
    assert resultado.rebaixamentos == []


async def test_limiar_unico_com_efeito_proprio_e_uma_faixa_aberta() -> None:
    texto = "Acima de R$ 40 mil, bônus de R$ 3500"
    elemento = faixa(texto, "40000", None, "3500")
    elemento["limite_inferior"] = lastro("40000", "R$ 40 mil")

    resultado = await extrair([elemento], texto)

    [unica] = especificacoes(resultado)
    assert unica["construto"] == "faixa_valor"
    assert (unica["limite_inferior"], unica["limite_superior"]) == (40000, LIMITE_SUPERIOR_ABERTO)


async def test_faixas_com_lacuna_saem_como_ditas() -> None:
    resultado = await extrair(FAIXAS[:2], TEXTO_FAIXAS)

    primeira, segunda = especificacoes(resultado)
    assert (primeira["limite_superior"], segunda["limite_inferior"]) == (50000, 50001)


async def test_faixa_de_loja_vira_generico_com_o_escopo_e_os_limites_em_campos() -> None:
    texto = (
        "Para os gerentes, vendas totais de loja acima de R$ 120 mil fazem jus a bônus de R$ 5000"
    )
    elemento = {
        "construto_pretendido": "generico",
        "descricao": texto,
        "trecho": texto,
        "campos": {
            "escopo": "loja",
            "limite_inferior": Decimal("120000"),
            "bonus": Decimal("5000"),
        },
    }

    resultado = await extrair([elemento], texto)

    assert especificacoes(resultado) == [
        {
            "ref": "elem.1",
            "construto": "generico",
            "descricao": texto,
            "campos": {"escopo": "loja", "limite_inferior": 120000, "bonus": 5000},
        }
    ]


async def test_campo_que_o_trecho_nao_traz_nao_acompanha_o_generico() -> None:
    texto = "Vendas totais de loja acima de R$ 120 mil fazem jus a bônus de R$ 5000"
    elemento = {
        "construto_pretendido": "generico",
        "descricao": texto,
        "trecho": texto,
        "campos": {"escopo": "marca", "limite_inferior": Decimal("999"), "Chave Inválida": "loja"},
    }

    resultado = await extrair([elemento], texto)

    [generico] = especificacoes(resultado)
    assert "campos" not in generico


async def test_faixa_sem_efeito_vira_generico() -> None:
    elemento = FAIXAS[0].copy()
    del elemento["efeito"]

    resultado = await extrair([elemento], TEXTO_FAIXAS)

    assert [e["construto"] for e in especificacoes(resultado)] == ["generico"]
    assert motivos(resultado) == ["campo_obrigatorio_ausente"]


async def test_limite_sem_lastro_vira_generico() -> None:
    elemento = faixa("40000 até 50000, R$ 3500", "40000", "50000", "3500")
    elemento["limite_superior"] = {"valor": Decimal("55000"), "trecho": "50000"}

    resultado = await extrair([elemento], TEXTO_FAIXAS)

    assert [e["construto"] for e in especificacoes(resultado)] == ["generico"]
    assert motivos(resultado) == ["valor_sem_lastro"]


@pytest.mark.parametrize(
    ("alteracoes", "motivo"),
    [
        ({"limite_superior": lastro("60000", "60000")}, "campo_obrigatorio_ausente"),
        ({"trecho": "60001, R$ 4500", "descricao": "60001, R$ 4500"}, "campo_obrigatorio_ausente"),
    ],
    ids=["aberta_com_limite_superior", "aberta_sem_palavra_de_abertura"],
)
async def test_faixa_aberta_inconsistente_vira_generico(
    alteracoes: dict[str, Any], motivo: str
) -> None:
    elemento = {**FAIXAS[2], **alteracoes}

    resultado = await extrair([elemento], TEXTO_FAIXAS)

    assert [e["construto"] for e in especificacoes(resultado)] == ["generico"]
    assert motivos(resultado) == [motivo]


async def test_faixa_fechada_sem_limite_superior_vira_generico() -> None:
    elemento = {**FAIXAS[0], "faixa_aberta": False}
    del elemento["limite_superior"]

    resultado = await extrair([elemento], TEXTO_FAIXAS)

    assert [e["construto"] for e in especificacoes(resultado)] == ["generico"]
    assert motivos(resultado) == ["campo_obrigatorio_ausente"]


def limiar_aberto(texto: str) -> dict[str, Any]:
    elemento = faixa(texto, "40000", None, "3500")
    elemento["limite_inferior"] = lastro("40000", "R$ 40 mil")
    return elemento


@pytest.mark.parametrize(
    "texto",
    [
        "Quem atingir a meta e vender acima de R$ 40 mil recebe bônus de R$ 3500",
        "Acima de R$ 40 mil, bônus de R$ 3500, desde que o colaborador esteja ativo",
        "Acima de R$ 40 mil e com ticket médio acima de R$ 800, bônus de R$ 3500",
        "Acima de R$ 40 mil, bônus de R$ 3500, salvo para os gerentes",
    ],
    ids=["meta", "desde_que", "ticket", "excecao"],
)
async def test_faixa_com_outra_condicao_fica_no_generico_com_o_trecho_inteiro(texto: str) -> None:
    resultado = await extrair([limiar_aberto(texto)], texto)

    [generico] = especificacoes(resultado)
    assert generico["construto"] == "generico"
    assert generico["descricao"] == texto
    assert motivos(resultado) == ["termo_ambiguo"]


@pytest.mark.parametrize(
    "texto",
    [
        "Caso venda acima de R$ 40 mil, bônus de R$ 3500",
        "Se o colaborador vender acima de R$ 40 mil, bônus de R$ 3500",
        "Quando as vendas passarem de R$ 40 mil, acima disso o bônus é de R$ 3500",
    ],
    ids=["caso", "se", "quando"],
)
async def test_palavra_que_introduz_a_propria_faixa_nao_a_rebaixa(texto: str) -> None:
    resultado = await extrair([limiar_aberto(texto)], texto)

    [unica] = especificacoes(resultado)
    assert unica["construto"] == "faixa_valor"
    assert resultado.rebaixamentos == []
