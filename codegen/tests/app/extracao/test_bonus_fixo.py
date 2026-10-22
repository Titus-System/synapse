from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest

from app.extracao.modelos import ResultadoExtracao
from app.extracao.motor import extrair_regra
from tests.app.extracao.test_motor import METADADOS, modelo_falso

TEXTO_LISTA = "Conceder bônus fixo de R$ 500 para as matrículas MATRIC-422 e MATRIC-517"
TEXTO_FILTRO = "Os admitidos até o dia 10/10 no cargo 100 terão um bônus de R$ 1.000"
ANO_UNICO = ["2025-10", "2025-11"]


def lastro(valor: Any, trecho: str) -> dict[str, Any]:
    return {"valor": valor, "trecho": trecho}


def rascunho_lista(**alteracoes: Any) -> dict[str, Any]:
    return {
        "construto_pretendido": "bonus_fixo",
        "descricao": TEXTO_LISTA,
        "trecho": TEXTO_LISTA,
        "tipo_alvo": "lista",
        "matriculas": ["MATRIC-422", "MATRIC-517"],
        "valor": lastro(Decimal("500"), "R$ 500"),
        **alteracoes,
    }


def rascunho_filtro(**alteracoes: Any) -> dict[str, Any]:
    return {
        "construto_pretendido": "bonus_fixo",
        "descricao": TEXTO_FILTRO,
        "trecho": TEXTO_FILTRO,
        "tipo_alvo": "filtro",
        "criterios": {"cargo": "100", "admitido_ate": "2025-10-10"},
        "valor": lastro(Decimal("1000"), "R$ 1.000"),
        **alteracoes,
    }


async def extrair(
    elemento: dict[str, Any], texto: str, competencias: Sequence[str] = ANO_UNICO
) -> ResultadoExtracao:
    modelo = modelo_falso({"nucleo": {}, "elementos": [elemento], "parametros": {}})
    return await extrair_regra(texto, competencias, modelo=modelo, metadados_modelo=METADADOS)


def elementos(resultado: ResultadoExtracao) -> list[Any]:
    regra: Any = resultado.representacao.para_contrato()
    return list(regra["especificacoes"])


async def test_lista_de_matriculas_vira_bonus_fixo() -> None:
    resultado = await extrair(rascunho_lista(), TEXTO_LISTA)

    assert elementos(resultado) == [
        {
            "ref": "elem.1",
            "construto": "bonus_fixo",
            "alvo": {"tipo": "lista", "valor": ["MATRIC-422", "MATRIC-517"]},
            "valor": Decimal("500"),
        }
    ]
    assert resultado.rebaixamentos == []


async def test_filtro_por_cargo_e_admissao_usa_o_ano_das_competencias() -> None:
    resultado = await extrair(rascunho_filtro(), TEXTO_FILTRO)

    assert elementos(resultado) == [
        {
            "ref": "elem.1",
            "construto": "bonus_fixo",
            "alvo": {"tipo": "filtro", "valor": {"cargo": "100", "admitido_ate": "2025-10-10"}},
            "valor": Decimal("1000"),
        }
    ]
    assert resultado.rebaixamentos == []


@pytest.mark.parametrize(
    ("texto", "matriculas"),
    [
        ("Bônus fixo de R$ 500 para a matrícula 422", ["422"]),
        (
            "Bônus fixo de R$ 500 para as matrículas 422 e 517",
            ["422", "MATRIC-517"],
        ),
    ],
)
async def test_matricula_dita_so_com_o_numero_e_normalizada(
    texto: str, matriculas: list[dict[str, Any]]
) -> None:
    elemento = rascunho_lista(descricao=texto, trecho=texto, matriculas=matriculas)

    resultado = await extrair(elemento, texto)

    [bonus] = elementos(resultado)
    assert bonus["alvo"]["valor"][0] == "MATRIC-422"
    assert resultado.rebaixamentos == []


async def test_matricula_que_o_texto_nao_cita_nao_entra_no_alvo() -> None:
    elemento = rascunho_lista(matriculas=["MATRIC-422", "MATRIC-999", "901"])

    resultado = await extrair(elemento, TEXTO_LISTA)

    [bonus] = elementos(resultado)
    assert bonus["alvo"]["valor"] == ["MATRIC-422"]


async def test_numero_solto_sem_a_palavra_matricula_nao_e_matricula() -> None:
    texto = "Bônus fixo de R$ 500 para o cargo 422"
    elemento = rascunho_lista(descricao=texto, trecho=texto, matriculas=["MATRIC-422"])

    resultado = await extrair(elemento, texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["valor_sem_lastro"]


async def test_lista_sem_nenhuma_matricula_com_lastro_vira_generico() -> None:
    elemento = rascunho_lista(matriculas=["MATRIC-999"])

    resultado = await extrair(elemento, TEXTO_LISTA)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [(r.ref, r.motivo) for r in resultado.rebaixamentos] == [("elem.1", "valor_sem_lastro")]


async def test_criterio_fora_do_vocabulario_rebaixa_o_elemento() -> None:
    texto = "Os vendedores da loja 13 terão um bônus de R$ 1.000"
    elemento = rascunho_filtro(
        descricao=texto,
        trecho=texto,
        criterios={"loja": "13"},
    )

    resultado = await extrair(elemento, texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["construto_nao_habilitado"]


async def test_criterio_fora_do_vocabulario_junto_de_um_aceito_tambem_rebaixa() -> None:
    texto = "Os admitidos até 10/10 na loja 13 terão um bônus de R$ 1.000"
    elemento = rascunho_filtro(
        descricao=texto,
        trecho=texto,
        criterios={"admitido_ate": "2025-10-10", "loja": "13"},
    )

    resultado = await extrair(elemento, texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]


@pytest.mark.parametrize(
    ("trecho_valor", "valor"),
    [
        ("R$ 1.000", Decimal("1000")),
        ("R$1000", Decimal("1000")),
        ("1.000 reais", Decimal("1000")),
        ("mil reais", Decimal("1000")),
    ],
)
async def test_entende_as_formas_de_escrever_o_valor_em_reais(
    trecho_valor: str, valor: Decimal
) -> None:
    texto = f"Os admitidos até 10/10 no cargo 100 terão um bônus de {trecho_valor}"
    elemento = rascunho_filtro(descricao=texto, trecho=texto, valor=lastro(valor, trecho_valor))

    resultado = await extrair(elemento, texto)

    assert elementos(resultado)[0]["valor"] == valor


async def test_bonus_percentual_vira_generico() -> None:
    texto = "Conceder bônus de 5% sobre a venda para as matrículas MATRIC-422"
    elemento = rascunho_lista(
        descricao=texto,
        trecho=texto,
        matriculas=["MATRIC-422"],
        valor=lastro(Decimal("5"), "5%"),
    )

    resultado = await extrair(elemento, texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["campo_obrigatorio_ausente"]


async def test_valor_sem_lastro_vira_generico() -> None:
    elemento = rascunho_lista(valor=lastro(Decimal("700"), "R$ 500"))

    resultado = await extrair(elemento, TEXTO_LISTA)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["valor_sem_lastro"]


@pytest.mark.parametrize("campo", ["valor", "tipo_alvo"])
async def test_campo_obrigatorio_ausente_vira_generico(campo: str) -> None:
    elemento = rascunho_lista()
    del elemento[campo]

    resultado = await extrair(elemento, TEXTO_LISTA)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["campo_obrigatorio_ausente"]


@pytest.mark.parametrize(
    "elemento",
    [
        rascunho_lista(matriculas=[]),
        rascunho_filtro(criterios={}),
        rascunho_lista(tipo_alvo="filtro"),
        rascunho_filtro(matriculas=["MATRIC-422"]),
        rascunho_lista(criterios={"cargo": "100"}),
    ],
    ids=[
        "lista_vazia",
        "filtro_vazio",
        "tipo_diverge_do_alvo",
        "filtro_com_lista",
        "lista_com_filtro",
    ],
)
async def test_alvo_ausente_ou_inconsistente_vira_generico(elemento: dict[str, Any]) -> None:
    texto = f"{TEXTO_LISTA}. {TEXTO_FILTRO}. cargo 100"

    resultado = await extrair({**elemento, "trecho": TEXTO_LISTA, "descricao": TEXTO_LISTA}, texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["campo_obrigatorio_ausente"]


async def test_cargo_do_filtro_fora_do_vocabulario_vira_generico() -> None:
    texto = "Os admitidos até 10/10 no cargo 999 terão um bônus de R$ 1.000"
    elemento = rascunho_filtro(
        descricao=texto,
        trecho=texto,
        criterios={"cargo": "999"},
    )

    resultado = await extrair(elemento, texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["codigo_fora_do_vocabulario"]


async def test_data_sem_ano_com_competencias_de_anos_diferentes_vira_generico() -> None:
    resultado = await extrair(rascunho_filtro(), TEXTO_FILTRO, ["2025-12", "2026-01"])

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["periodo_nao_resolvido"]


async def test_ano_dito_no_texto_vale_mesmo_com_competencias_de_anos_diferentes() -> None:
    texto = "Os admitidos até o dia 10/10/2025 no cargo 100 terão um bônus de R$ 1.000"
    elemento = rascunho_filtro(
        descricao=texto,
        trecho=texto,
        criterios={
            "cargo": "100",
            "admitido_ate": "2025-10-10",
        },
    )

    resultado = await extrair(elemento, texto, ["2025-12", "2026-01"])

    assert elementos(resultado)[0]["alvo"]["valor"]["admitido_ate"] == "2025-10-10"


async def test_data_que_o_texto_nao_diz_vira_generico() -> None:
    elemento = rascunho_filtro(
        criterios={
            "cargo": "100",
            "admitido_ate": "2025-10-11",
        }
    )

    resultado = await extrair(elemento, TEXTO_FILTRO)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["valor_sem_lastro"]


async def test_percentual_no_trecho_do_elemento_vira_generico_mesmo_com_valor_sem_o_simbolo() -> (
    None
):
    texto = "Bônus de 5% para as matrículas 422 e 517"
    elemento = rascunho_lista(descricao=texto, trecho=texto, valor=lastro(Decimal("5"), "5"))

    resultado = await extrair(elemento, texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["campo_obrigatorio_ausente"]


@pytest.mark.parametrize("direcao", ["a partir de", "depois de", "antes de", "desde"])
async def test_admissao_em_outra_direcao_que_nao_ate_vira_generico(direcao: str) -> None:
    texto = f"Os admitidos {direcao} 10/10 no cargo 100 terão um bônus de R$ 1.000"

    resultado = await extrair(rascunho_filtro(descricao=texto, trecho=texto), texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


@pytest.mark.parametrize(
    "texto",
    [
        "Não conceder bônus fixo de R$ 500 para as matrículas MATRIC-422 e MATRIC-517",
        "Ninguém além das matrículas MATRIC-422 e MATRIC-517 recebe bônus fixo de R$ 500",
        "Bônus fixo de R$ 500 para as matrículas MATRIC-422 e MATRIC-517, exceto a MATRIC-517",
    ],
)
async def test_bonus_negado_ou_com_excecao_vira_generico(texto: str) -> None:
    resultado = await extrair(rascunho_lista(descricao=texto, trecho=texto), texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


async def test_admissao_negada_vira_generico() -> None:
    texto = "Os admitidos até 10/10 no cargo 100 não ganham bônus de R$ 1.000"

    resultado = await extrair(rascunho_filtro(descricao=texto, trecho=texto), texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


@pytest.mark.parametrize(
    "condicao",
    [
        "quando suas vendas individuais no mês forem iguais ou superiores a R$ 45.000,00",
        "para quem vender pelo menos R$ 45.000,00 no mês",
        "somente se completar cinco atendimentos no mês",
    ],
)
async def test_bonus_condicionado_nao_perde_o_requisito_ao_virar_tipado(condicao: str) -> None:
    texto = f"Para o cargo 100, pague um bônus fixo de R$ 400,00 {condicao}."
    elemento = rascunho_filtro(
        descricao=texto,
        trecho=texto,
        criterios={"cargo": "100"},
        valor=lastro(Decimal("400"), "R$ 400,00"),
    )

    resultado = await extrair(elemento, texto)

    assert elementos(resultado) == [{"ref": "elem.1", "construto": "generico", "descricao": texto}]
    assert [(r.ref, r.motivo) for r in resultado.rebaixamentos] == [("elem.1", "termo_ambiguo")]
