import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.extracao.construto import ContextoExtracao
from app.extracao.construtos.exclusao import converter
from app.extracao.modelos import ElementoRebaixadoError, ResultadoExtracao
from app.extracao.motor import extrair_regra
from tests.app.extracao.test_motor import METADADOS, modelo_falso

ARQUIVO = Path(__file__).resolve().parents[2] / "fixtures" / "corpus_exclusao.json"
CASOS: list[dict[str, Any]] = json.loads(ARQUIVO.read_text(encoding="utf-8"), parse_float=Decimal)
PUBLICADAS = ["2025-11"]


def lastro(valor: str, trecho: str) -> dict[str, str]:
    return {"valor": valor, "trecho": trecho}


def rascunho(trecho: str, dimensao: str, valores: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "construto_pretendido": "exclusao",
        "descricao": trecho,
        "trecho": trecho,
        "dimensao": dimensao,
        "valores": valores,
    }


async def extrair(
    elementos: list[dict[str, Any]], texto: str, competencias: Sequence[str] = PUBLICADAS
) -> ResultadoExtracao:
    modelo = modelo_falso({"nucleo": {}, "elementos": elementos, "parametros": {}})
    return await extrair_regra(texto, competencias, modelo=modelo, metadados_modelo=METADADOS)


def especificacoes(resultado: ResultadoExtracao) -> list[Any]:
    regra: Any = resultado.representacao.para_contrato()
    return list(regra["especificacoes"])


@pytest.mark.parametrize("caso", CASOS, ids=[c["id"] for c in CASOS])
async def test_caso_do_corpus_pelo_motor_com_modelo_falso(caso: dict[str, Any]) -> None:
    modelo = modelo_falso(caso["rascunho"])

    resultado = await extrair_regra(
        caso["texto"], caso["competencias_publicadas"], modelo=modelo, metadados_modelo=METADADOS
    )

    assert resultado.representacao.para_contrato() == caso["representacao_esperada"]
    assert resultado.parametros == caso["parametros_esperados"]
    assert [r.motivo for r in resultado.rebaixamentos] == (
        [caso["motivo_esperado"]] if caso["motivo_esperado"] else []
    )


async def test_nomes_do_mesmo_cargo_viram_um_unico_codigo() -> None:
    texto = "Exceto os gerentes"
    valores = [lastro("GERENTE DE LOJA", "gerentes"), lastro("GERENTE QUIOSQUE", "gerentes")]

    resultado = await extrair([rascunho(texto, "cargo", valores)], texto)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "exclusao", "dimensao": "cargo", "valores": ["150"]}
    ]


async def test_matricula_com_numero_de_loja_nao_vira_exclusao_de_loja() -> None:
    texto = "Comissão de 2%, exceto a matrícula 13"
    trecho = "exceto a matrícula 13"

    resultado = await extrair([rascunho(trecho, "loja", [lastro("13", "13")])], texto)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": trecho}
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["campo_obrigatorio_ausente"]


async def test_dimensao_matricula_nao_cabe_no_rascunho_e_vira_generico() -> None:
    texto = "Exceto a matrícula MATRIC-422"

    resultado = await extrair(
        [rascunho(texto, "matricula", [lastro("MATRIC-422", "MATRIC-422")])], texto
    )

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": texto}
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["campo_obrigatorio_ausente"]


@pytest.mark.parametrize(
    "alteracao",
    [
        {"valores": []},
        {"valores": ["13"]},
        {"dimensao": None},
        {"valores": None},
    ],
    ids=["valores_vazios", "valor_sem_trecho", "sem_dimensao", "sem_valores"],
)
async def test_rascunho_incompleto_vira_generico(alteracao: dict[str, Any]) -> None:
    texto = "Para todas as lojas, exceto a 13"
    elemento = rascunho("exceto a 13", "loja", [lastro("13", "13")])
    elemento.update(alteracao)
    elemento = {chave: valor for chave, valor in elemento.items() if valor is not None}

    resultado = await extrair([elemento], texto)

    assert [e["construto"] for e in especificacoes(resultado)] == ["generico"]
    assert [r.motivo for r in resultado.rebaixamentos] == ["campo_obrigatorio_ausente"]


async def test_codigo_sem_lastro_rebaixa_a_exclusao_inteira() -> None:
    texto = "Para todas as lojas, exceto a 13"
    valores = [lastro("13", "13"), lastro("58", "58")]

    resultado = await extrair([rascunho("exceto a 13", "loja", valores)], texto)

    assert especificacoes(resultado) == [
        {
            "ref": "elem.1",
            "construto": "generico",
            "descricao": "exceto a 13",
            "campos": {"dimensao": "loja", "valores": ["13"]},
        }
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["valor_sem_lastro"]


@pytest.mark.parametrize(
    ("dimensao", "outra_parte", "trecho", "codigo", "outro_codigo"),
    [
        ("loja", "loja 13", "exceto a loja 58", "58", "13"),
        ("marca", "marca 10", "exceto a marca 20", "20", "10"),
        ("cargo", "cargo 150", "exceto o cargo 300", "300", "150"),
    ],
)
async def test_codigo_de_outra_parte_do_texto_rebaixa_a_exclusao_inteira(
    dimensao: str, outra_parte: str, trecho: str, codigo: str, outro_codigo: str
) -> None:
    texto = f"Comissão de 2% para {outra_parte}, {trecho}"
    valores = [lastro(codigo, codigo), lastro(outro_codigo, outra_parte)]

    resultado = await extrair([rascunho(trecho, dimensao, valores)], texto)

    assert especificacoes(resultado) == [
        {
            "ref": "elem.1",
            "construto": "generico",
            "descricao": trecho,
            "campos": {"dimensao": dimensao, "valores": [codigo]},
        }
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["valor_sem_lastro"]


@pytest.mark.parametrize(
    ("dimensao", "codigo", "desconhecido"),
    [("loja", "13", "99"), ("marca", "10", "99"), ("cargo", "150", "999")],
)
async def test_codigo_desconhecido_nao_e_substituido_por_outro_do_trecho(
    dimensao: str, codigo: str, desconhecido: str
) -> None:
    trecho = f"Exceto {dimensao} {codigo} e {desconhecido}"
    valores = [lastro(codigo, codigo), lastro(desconhecido, trecho)]

    resultado = await extrair([rascunho(trecho, dimensao, valores)], trecho)

    assert especificacoes(resultado) == [
        {
            "ref": "elem.1",
            "construto": "generico",
            "descricao": trecho,
            "campos": {"dimensao": dimensao, "valores": [codigo]},
        }
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["codigo_fora_do_vocabulario"]


async def test_cargo_ambiguo_rebaixa_sem_escolher_um_codigo() -> None:
    texto = "Exceto os vendedores"

    resultado = await extrair([rascunho(texto, "cargo", [lastro("vendedor", "vendedores")])], texto)

    assert especificacoes(resultado) == [
        {
            "ref": "elem.1",
            "construto": "generico",
            "descricao": texto,
            "campos": {"dimensao": "cargo"},
        }
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


@pytest.mark.parametrize(
    "texto",
    [
        "Bônus de R$ 500 para todos, exceto os gerentes (150)",
        "Bônus de 500 reais para todos, exceto os gerentes (150)",
        "Acréscimo de 1% para todos, exceto os gerentes (150)",
        "Acréscimo de um por cento para todos, exceto os gerentes (150)",
    ],
)
async def test_excecao_junto_de_um_efeito_proprio_vira_generico(texto: str) -> None:
    resultado = await extrair([rascunho(texto, "cargo", [lastro("150", "gerentes (150)")])], texto)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": texto}
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


@pytest.mark.parametrize(
    "trecho",
    [
        "Este bônus não se aplica aos cargos de gerente",
        "O acréscimo não se aplica aos cargos de gerente",
        "Nesta faixa, exceto os gerentes",
        "O prêmio não se aplica aos gerentes",
    ],
)
async def test_excecao_de_um_efeito_sem_valor_nao_vira_exclusao_global(trecho: str) -> None:
    texto = f"Comissão de 2%. {trecho}."

    resultado = await extrair([rascunho(trecho, "cargo", [lastro("150", "gerente")])], texto)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": trecho}
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


@pytest.mark.parametrize(
    "efeito",
    [
        "Bônus de R$ 500 para todos",
        "Bônus de R$ 1.000,50 para todos",
        "Acréscimo de 0.01 em fração",
        "Na faixa acima de R$ 50 mil",
    ],
)
@pytest.mark.parametrize("pontuacao", ["", ".", "!", "?"])
async def test_recorte_da_excecao_nao_perde_o_alcance_do_efeito(
    efeito: str, pontuacao: str
) -> None:
    trecho = f"exceto os gerentes (150){pontuacao}"
    texto = f"Comissão de 2%. {efeito}, {trecho}"

    resultado = await extrair([rascunho(trecho, "cargo", [lastro("150", "gerentes (150)")])], texto)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": trecho}
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


@pytest.mark.parametrize(
    "texto",
    [
        "Bônus de R$ 500 para a matrícula 422. A regra não se aplica aos gerentes (150).",
        "A regra não se aplica aos gerentes (150). Bônus de R$ 500 para a matrícula 422.",
    ],
)
async def test_exclusao_da_regra_nao_herda_um_bonus_de_outra_frase(texto: str) -> None:
    trecho = "A regra não se aplica aos gerentes (150)."

    resultado = await extrair(
        [rascunho(trecho, "cargo", [lastro("gerente", "gerentes (150)")])], texto
    )

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "exclusao", "dimensao": "cargo", "valores": ["150"]}
    ]
    assert resultado.rebaixamentos == []


@pytest.mark.parametrize("sujeito", ["A regra inteira", "Toda a regra", "A regra como um todo"])
@pytest.mark.parametrize("inclusao", ["", ", inclusive o bônus,"])
@pytest.mark.parametrize("separador", [". ", "; "])
async def test_alcance_global_explicito_preserva_a_exclusao(
    sujeito: str, inclusao: str, separador: str
) -> None:
    trecho = f"{sujeito}{inclusao} não se aplica aos gerentes (150)"
    texto = f"Comissão de 2%. Bônus de R$ 500 para a matrícula 422{separador}{trecho}."

    resultado = await extrair([rascunho(trecho, "cargo", [lastro("150", "gerentes (150)")])], texto)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "exclusao", "dimensao": "cargo", "valores": ["150"]}
    ]
    assert resultado.rebaixamentos == []


@pytest.mark.parametrize(
    "trecho",
    [
        "Ele não se aplica aos gerentes (150)",
        "Esse benefício não se aplica aos gerentes (150)",
        "Não se aplica aos gerentes (150)",
        "exceto os gerentes (150)",
    ],
)
@pytest.mark.parametrize("separador", [". ", "; ", "! ", "? "])
async def test_retoma_do_bonus_anterior_nao_vira_exclusao_global(
    trecho: str, separador: str
) -> None:
    texto = f"Comissão de 2%. Bônus de R$ 500 para a matrícula 422{separador}{trecho}."

    resultado = await extrair([rascunho(trecho, "cargo", [lastro("150", "gerentes (150)")])], texto)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": trecho}
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


async def test_mencao_a_regra_inteira_nao_muda_o_sujeito_da_excecao() -> None:
    trecho = "A regra inteira tem um bônus que não se aplica aos gerentes (150)"

    resultado = await extrair(
        [rascunho(trecho, "cargo", [lastro("150", "gerentes (150)")])], trecho
    )

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": trecho}
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


@pytest.mark.parametrize("qualificador", ["exceto no bônus", "apenas no bônus"])
@pytest.mark.parametrize("recortar", [False, True])
async def test_restricao_ao_bonus_nao_e_sobreposta_pela_mencao_a_regra_inteira(
    qualificador: str, recortar: bool
) -> None:
    frase = f"A regra inteira não se aplica aos gerentes (150), {qualificador}"
    trecho = "não se aplica aos gerentes (150)" if recortar else frase

    resultado = await extrair([rascunho(trecho, "cargo", [lastro("150", "gerentes (150)")])], frase)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "generico", "descricao": trecho}
    ]
    assert [r.motivo for r in resultado.rebaixamentos] == ["termo_ambiguo"]


async def test_retoma_da_regra_nao_herda_um_bonus_mais_antigo() -> None:
    trecho = "Ela não se aplica aos gerentes (150)"
    texto = f"Bônus de R$ 500 para a matrícula 422. A regra tem comissão de 2%. {trecho}."

    resultado = await extrair([rascunho(trecho, "cargo", [lastro("150", "gerentes (150)")])], texto)

    assert especificacoes(resultado) == [
        {"ref": "elem.1", "construto": "exclusao", "dimensao": "cargo", "valores": ["150"]}
    ]
    assert resultado.rebaixamentos == []


def test_rebaixamento_nao_carrega_o_texto_do_usuario() -> None:
    texto = "Para todas as lojas, exceto a 13 e a LOJA_PRIVADA"
    elemento = rascunho(
        "exceto a 13 e a LOJA_PRIVADA",
        "loja",
        [lastro("13", "13"), lastro("LOJA_PRIVADA", "LOJA_PRIVADA")],
    )

    with pytest.raises(ElementoRebaixadoError) as erro:
        converter(elemento, ContextoExtracao(texto, PUBLICADAS))

    assert erro.value.args == ("codigo_fora_do_vocabulario",)
    assert erro.value.campos == {"dimensao": "loja", "valores": ["13"]}
    assert erro.value.__cause__ is None
    assert erro.value.__context__ is None


async def test_prompt_traz_instrucoes_e_exemplos_de_exclusao() -> None:
    texto = CASOS[0]["texto"]

    resultado = await extrair(CASOS[0]["rascunho"]["elementos"], texto)

    instrucoes = json.loads(resultado.chamada.prompt)["instrucoes_fixas_do_sistema"]
    variantes = instrucoes["schema_saida"]["properties"]["elementos"]["items"]["anyOf"]
    [variante] = [
        v for v in variantes if v["properties"]["construto_pretendido"].get("enum") == ["exclusao"]
    ]
    dimensao = variante["properties"]["dimensao"]["description"]
    assert "Condição sobre a venda" in dimensao and "é condicao_limiar" in dimensao
    assert "'" not in dimensao
    assert "{valor, trecho} por código" in variante["properties"]["valores"]["description"]
    [exclusao] = [i for i in instrucoes["construtos_habilitados"] if i.startswith("exclusao:")]
    for termo in (
        "loja, marca ou cargo",
        "Um elemento por dimensão",
        "{valor, trecho}",
        "'Todas as lojas, menos a 13' só exclui",
        "'Somente a loja 13' só inclui: é núcleo",
        "fica no núcleo mesmo quando também é excluído",
        "nunca corrigida aqui",
        "com exceção dos gerentes (150)",
        "Esta regra não se aplica aos cargos de gerente",
        "exceto a 13 e a 58",
        "'Pague 2% nas lojas 13 e 58, exceto a loja 13' -> nucleo.loja com 13 e 58",
        "trecho 'Não vale para a loja 5', com o N maiúsculo como no texto",
        "exceto a matrícula MATRIC-422",
        "só para uma de várias regras do texto",
        "Quando o texto tem várias regras, o núcleo é só a primeira",
        "loja 7 e 4% não entram no núcleo",
        "'Este bônus não se aplica aos cargos de gerente' é generico",
        "Não recorte só a exceção de uma frase que também define o efeito",
        "O sujeito da exclusão define seu alcance",
        "mesmo separados por ponto ou ponto e vírgula",
    ):
        assert termo in exclusao
