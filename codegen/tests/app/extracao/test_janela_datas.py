from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest

from app.extracao.modelos import ResultadoExtracao
from app.extracao.motor import extrair_regra
from tests.app.extracao.test_motor import METADADOS, modelo_falso

TEXTO = "Todas as vendas no período de 24/11 a 30/11 terão um acréscimo de +1% (Black Friday)"
ANO_UNICO = ["2025-11", "2025-12"]


def efeito(tipo: str, valor: str, trecho: str) -> dict[str, Any]:
    return {"tipo": tipo, "valor": {"valor": Decimal(valor), "trecho": trecho}}


def rascunho(**alteracoes: Any) -> dict[str, Any]:
    return {
        "construto_pretendido": "janela_datas",
        "descricao": TEXTO,
        "trecho": TEXTO,
        "data_inicial": "2025-11-24",
        "data_final": "2025-11-30",
        "efeito": efeito("acrescimo_pct", "0.01", "+1%"),
        **alteracoes,
    }


async def extrair(
    elemento: dict[str, Any],
    texto: str = TEXTO,
    competencias: Sequence[str] = ANO_UNICO,
    nucleo: dict[str, Any] | None = None,
) -> ResultadoExtracao:
    modelo = modelo_falso({"nucleo": nucleo or {}, "elementos": [elemento], "parametros": {}})
    return await extrair_regra(texto, competencias, modelo=modelo, metadados_modelo=METADADOS)


def elementos(resultado: ResultadoExtracao) -> list[Any]:
    regra: Any = resultado.representacao.para_contrato()
    return list(regra["especificacoes"])


def motivos(resultado: ResultadoExtracao) -> list[str]:
    return [r.motivo for r in resultado.rebaixamentos]


async def test_janela_da_black_friday_vira_janela_datas() -> None:
    resultado = await extrair(rascunho())

    assert elementos(resultado) == [
        {
            "ref": "elem.1",
            "construto": "janela_datas",
            "data_inicial": "2025-11-24",
            "data_final": "2025-11-30",
            "efeito": {"tipo": "acrescimo_pct", "valor": Decimal("0.01")},
        }
    ]
    assert resultado.rebaixamentos == []


async def test_janela_dos_gerentes_mantem_o_cargo_no_nucleo() -> None:
    texto = "Para os Gerentes, todas as vendas de 24/11 a 30/11 terão um acréscimo de +0,5%"
    elemento = rascunho(
        descricao=texto,
        trecho=texto,
        efeito=efeito("acrescimo_pct", "0.005", "+0,5%"),
    )

    resultado = await extrair(
        elemento, texto, nucleo={"cargo": [{"valor": "150", "trecho": "Gerentes"}]}
    )

    regra: Any = resultado.representacao.para_contrato()
    assert regra["nucleo"] == {"cargo": ["150"]}
    assert regra["especificacoes"][0]["efeito"]["valor"] == Decimal("0.005")


async def test_dia_unico_repete_a_data_e_aceita_bonus_fixo() -> None:
    texto = "No dia 28/11, bônus de R$ 200"
    elemento = rascunho(
        descricao=texto,
        trecho=texto,
        data_inicial="2025-11-28",
        data_final="2025-11-28",
        efeito=efeito("bonus_fixo", "200", "R$ 200"),
    )

    resultado = await extrair(elemento, texto)

    [janela] = elementos(resultado)
    assert (janela["data_inicial"], janela["data_final"]) == ("2025-11-28", "2025-11-28")
    assert janela["efeito"] == {"tipo": "bonus_fixo", "valor": Decimal("200")}


async def test_substituicao_do_percentual() -> None:
    texto = "De 24/11 a 30/11 o percentual passa a ser 3%"
    elemento = rascunho(
        descricao=texto,
        trecho=texto,
        efeito=efeito("substituicao_pct", "0.03", "3%"),
    )

    resultado = await extrair(elemento, texto)

    assert elementos(resultado)[0]["efeito"] == {
        "tipo": "substituicao_pct",
        "valor": Decimal("0.03"),
    }


async def test_janela_invertida_sai_como_dita() -> None:
    texto = "Vendas de 30/11 a 24/11 terão +1%"
    elemento = rascunho(
        descricao=texto,
        trecho=texto,
        data_inicial="2025-11-30",
        data_final="2025-11-24",
    )

    resultado = await extrair(elemento, texto)

    [janela] = elementos(resultado)
    assert (janela["data_inicial"], janela["data_final"]) == ("2025-11-30", "2025-11-24")


async def test_evento_sem_datas_no_texto_nao_ganha_datas_inventadas() -> None:
    texto = "Na Black Friday, +1%"
    elemento = rascunho(descricao=texto, trecho=texto)

    resultado = await extrair(elemento, texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert motivos(resultado) == ["valor_sem_lastro"]


async def test_data_sem_ano_com_competencias_de_anos_diferentes_vira_generico() -> None:
    resultado = await extrair(rascunho(), competencias=["2025-12", "2026-01"])

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert motivos(resultado) == ["periodo_nao_resolvido"]


async def test_datas_que_o_trecho_nao_diz_viram_generico() -> None:
    resultado = await extrair(rascunho(data_final="2025-11-29"))

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert motivos(resultado) == ["valor_sem_lastro"]


async def test_trecho_com_tres_datas_vira_generico() -> None:
    texto = "Vendas de 24/11 a 30/11 e 05/12 terão +1%"
    elemento = rascunho(descricao=texto, trecho=texto)

    resultado = await extrair(elemento, texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]


async def test_numero_do_dia_nao_valida_percentual_sem_conversao() -> None:
    texto = "De 1/11 a 30/11 haverá +1%"
    elemento = rascunho(
        descricao=texto,
        trecho=texto,
        data_inicial="2025-11-01",
        efeito=efeito("acrescimo_pct", "1", texto),
    )

    resultado = await extrair(elemento, texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert motivos(resultado) == ["valor_sem_lastro"]


async def test_efeitos_trocados_entre_janelas_sao_rebaixados() -> None:
    novembro = "De 24/11 a 30/11 haverá +1%"
    dezembro = "De 01/12 a 05/12 haverá +3%"
    modelo = modelo_falso(
        {
            "nucleo": {},
            "parametros": {},
            "elementos": [
                rascunho(
                    descricao=novembro,
                    trecho=novembro,
                    efeito=efeito("acrescimo_pct", "0.03", "+3%"),
                ),
                rascunho(
                    descricao=dezembro,
                    trecho=dezembro,
                    data_inicial="2025-12-01",
                    data_final="2025-12-05",
                    efeito=efeito("acrescimo_pct", "0.01", "+1%"),
                ),
            ],
        }
    )

    resultado = await extrair_regra(
        f"{novembro}. {dezembro}.", ANO_UNICO, modelo=modelo, metadados_modelo=METADADOS
    )

    assert elementos(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": novembro},
        {"ref": "elem.2", "construto": "generico", "descricao": dezembro},
    ]
    assert motivos(resultado) == ["valor_sem_lastro", "valor_sem_lastro"]


@pytest.mark.parametrize(
    ("trecho", "data_final"),
    [
        ("De 24/11 a 31/11 haverá +1%", "2025-11-24"),
        ("De 31/11 a 24/11 haverá +1%", "2025-11-24"),
        ("De 24/11 a 30/11 e 31/11 haverá +1%", "2025-11-30"),
    ],
)
async def test_data_invalida_nao_e_descartada_para_aceitar_o_restante_da_janela(
    trecho: str, data_final: str
) -> None:
    elemento = rascunho(descricao=trecho, trecho=trecho, data_final=data_final)

    resultado = await extrair(elemento, trecho)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert motivos(resultado) == ["valor_sem_lastro"]


async def test_janela_sem_efeito_vira_generico() -> None:
    elemento = rascunho()
    del elemento["efeito"]

    resultado = await extrair(elemento)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert motivos(resultado) == ["campo_obrigatorio_ausente"]


async def test_efeito_que_so_caberia_em_acrescimo_base_vira_generico() -> None:
    elemento = rascunho(efeito=efeito("acrescimo_base", "1000", "R$ 1.000"))

    resultado = await extrair(elemento)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert motivos(resultado) == ["campo_obrigatorio_ausente"]


@pytest.mark.parametrize(
    ("alteracao", "esperado"),
    [
        (efeito("acrescimo_pct", "0.02", "+1%"), "valor_sem_lastro"),
        (efeito("acrescimo_pct", "1", "R$ 1"), "valor_sem_lastro"),
        (efeito("bonus_fixo", "1", "+1%"), "campo_obrigatorio_ausente"),
    ],
    ids=["valor_diferente_do_trecho", "percentual_sem_marcador", "bonus_com_percentual"],
)
async def test_efeito_sem_lastro_ou_de_outra_grandeza_vira_generico(
    alteracao: dict[str, Any], esperado: str
) -> None:
    texto = f"{TEXTO} R$ 1"

    resultado = await extrair(rascunho(efeito=alteracao), texto)

    assert [e["construto"] for e in elementos(resultado)] == ["generico"]
    assert motivos(resultado) == [esperado]
