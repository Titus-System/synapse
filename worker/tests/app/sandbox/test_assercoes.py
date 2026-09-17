from copy import deepcopy
from typing import Any

import pytest

from app.sandbox.assercoes import AssercaoVioladaError, TabelaApurada, finalizar_apuracao
from app.sandbox.regras_base import apurar
from tests.app.sandbox.test_regras_base import evento, rh, taxa, venda


def exemplo() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pessoas = [rh("VENDEDOR"), rh("GERENTE", cod_cargo=150)]
    vendas = [venda("VENDEDOR", 1000)]
    tabela = apurar(pessoas, vendas, [taxa(0.10), taxa(0.01, cod_cargo=150)], [], "2025-11")
    assert isinstance(tabela, TabelaApurada)
    contexto: dict[str, Any] = {
        "competencia": "2025-11",
        "rh": pessoas,
        "vendas": vendas,
        "eventos_rh": [],
        "por_loja": {"1": 110.0},
    }
    return deepcopy(list(tabela)), contexto


def test_apurar_executa_as_tres_e_incorpora_desfecho_sem_veredito() -> None:
    resultado = apurar([rh("A")], [venda("A", 1000)], [taxa(0.10)], [], "2025-11")
    assert isinstance(resultado, TabelaApurada)
    assert resultado.resultado_apuracao == {
        "status": "sucesso",
        "veredito": None,
        "competencia": "2025-11",
        "assercoes": [
            {"nome": "sem_comissao_negativa", "resultado": "ok", "detalhe": None},
            {"nome": "sem_comissao_sem_venda", "resultado": "ok", "detalhe": None},
            {"nome": "soma_loja_igual_soma_matricula", "resultado": "ok", "detalhe": None},
        ],
        "total": 100.0,
        "por_loja": {"1": 100.0},
        "por_matricula": {"A": 100.0},
    }


@pytest.mark.parametrize("campo", ["Data_Admiss", "data_admiss"])
@pytest.mark.parametrize("data_corrigida,comissao", [("2025-10-01", 100.0), ("2025-11-15", 50.0)])
def test_admissao_corrigida_pelo_rh_e_valida_na_apuracao_e_nas_assercoes(
    campo: str, data_corrigida: str, comissao: float
) -> None:
    pessoas = [rh("A", data_admiss="2025-12-01")]
    eventos = [
        evento(
            "CORR-ADM",
            "correcao_cadastral",
            "A",
            None,
            None,
            detalhes={"campo": campo, "valor_novo": data_corrigida},
        )
    ]
    entradas_antes = deepcopy((pessoas, eventos))

    resultado = apurar(pessoas, [venda("A", 1000)], [taxa(0.10)], eventos, "2025-11")

    assert isinstance(resultado, TabelaApurada)
    assert resultado[0]["comissao"] == comissao
    assert resultado.resultado_apuracao["status"] == "sucesso"
    assert all(a["resultado"] == "ok" for a in resultado.resultado_apuracao["assercoes"])
    assert (pessoas, eventos) == entradas_antes


@pytest.mark.parametrize("campo", ["Data_Admiss", "data_admiss"])
def test_correcao_que_adia_admissao_invalida_comissao_na_competencia(campo: str) -> None:
    linhas, contexto = exemplo()
    contexto["eventos_rh"] = [
        evento(
            "CORR-ADM",
            "correcao_cadastral",
            "VENDEDOR",
            None,
            None,
            detalhes={"campo": campo, "valor_novo": "2025-12-01"},
        )
    ]

    resultado = finalizar_apuracao(linhas, **contexto)

    assert resultado["status"] == "assercao_violada"
    assert resultado["assercoes"][1]["resultado"] == "violada"
    assert "matrícula VENDEDOR" in str(resultado["assercoes"][1]["detalhe"])
    assert "admitida após a competência" in str(resultado["assercoes"][1]["detalhe"])


@pytest.mark.parametrize(
    "matricula,competencia_origem",
    [("VENDEDOR", "2025-12"), ("OUTRO", "2025-11")],
)
def test_correcao_futura_ou_de_outra_pessoa_nao_justifica_admissao(
    matricula: str, competencia_origem: str
) -> None:
    linhas, contexto = exemplo()
    contexto["rh"][0]["data_admiss"] = "2025-12-01"
    contexto["eventos_rh"] = [
        evento(
            "CORR-ADM",
            "correcao_cadastral",
            matricula,
            None,
            None,
            competencia_origem=competencia_origem,
            detalhes={"campo": "Data_Admiss", "valor_novo": "2025-10-01"},
        )
    ]

    resultado = finalizar_apuracao(linhas, **contexto)

    assert resultado["assercoes"][1]["resultado"] == "violada"
    assert "admitida após a competência" in str(resultado["assercoes"][1]["detalhe"])


def test_correcoes_de_admissao_respeitam_competencia_e_id_independente_da_ordem() -> None:
    eventos = [
        evento(
            identificador,
            "correcao_cadastral",
            "A",
            None,
            None,
            competencia_origem=competencia_origem,
            detalhes={"campo": "Data_Admiss", "valor_novo": data_corrigida},
        )
        for identificador, competencia_origem, data_corrigida in [
            ("B", "2025-11", "2025-10-01"),
            ("A", "2025-11", "2025-12-01"),
            ("Z", "2025-10", "2025-12-15"),
        ]
    ]

    resultado = apurar(
        [rh("A", data_admiss="2025-12-01")],
        [venda("A", 1000)],
        [taxa(0.10)],
        eventos,
        "2025-11",
    )

    assert isinstance(resultado, TabelaApurada)
    assert resultado[0]["comissao"] == 100.0
    assert resultado.resultado_apuracao["status"] == "sucesso"


@pytest.mark.parametrize("valor", [-1, -0.001, float("nan"), float("inf"), True])
def test_comissao_negativa_ou_nao_finita_invalida_os_numeros(valor: object) -> None:
    linhas, contexto = exemplo()
    linhas[0]["comissao"] = valor
    resultado = finalizar_apuracao(linhas, **contexto)
    assert resultado["status"] == "assercao_violada"
    assert resultado["veredito"] is None
    assert resultado["total"] is resultado["por_loja"] is resultado["por_matricula"] is None
    assert len(resultado["assercoes"]) == 3
    falha = resultado["assercoes"][0]
    assert falha["resultado"] == "violada"
    assert "2025-11, linha 1, matrícula GERENTE, loja 1" in str(falha["detalhe"])


def test_apuracao_base_com_taxa_negativa_interrompe_com_excecao_estruturada() -> None:
    with pytest.raises(AssercaoVioladaError, match="sem_comissao_negativa") as erro:
        apurar([rh("A")], [venda("A", 1000)], [taxa(-0.10)], [], "2025-11")
    assert erro.value.resultado["status"] == "assercao_violada"
    assert len(erro.value.resultado["assercoes"]) == 3


@pytest.mark.parametrize("referencias", [[], [9999], [True]])
def test_comissao_sem_venda_ou_com_referencia_falsa_falha(referencias: list[object]) -> None:
    linhas, contexto = exemplo()
    linhas[1]["rastreabilidade"]["linhas_vendas"] = referencias
    resultado = finalizar_apuracao(linhas, **contexto)
    assert resultado["assercoes"][1]["resultado"] == "violada"
    assert "VENDEDOR" in str(resultado["assercoes"][1]["detalhe"])


def test_venda_de_outra_matricula_nao_prova_origem() -> None:
    linhas, contexto = exemplo()
    contexto["vendas"][0]["matricula"] = "OUTRA"
    assert finalizar_apuracao(linhas, **contexto)["assercoes"][1]["resultado"] == "violada"


def test_gerente_sem_venda_propria_usa_vendas_da_loja() -> None:
    linhas, contexto = exemplo()
    assert linhas[0]["matricula"] == "GERENTE"
    assert finalizar_apuracao(linhas, **contexto)["assercoes"][1]["resultado"] == "ok"
    contexto["vendas"][0]["cod_loja"] = 2
    assert finalizar_apuracao(linhas, **contexto)["assercoes"][1]["resultado"] == "violada"


def test_piso_sem_venda_tem_origem_no_evento_remunerado() -> None:
    resultado = apurar(
        [rh("A")],
        [],
        [taxa(0.025)],
        [evento("E", "afastamento", "A", "2025-11-01", "2025-11-10")],
        "2025-11",
    )
    assert isinstance(resultado, TabelaApurada)
    assert resultado[0]["comissao"] == 3500.0
    assert resultado.resultado_apuracao["assercoes"][1]["resultado"] == "ok"


@pytest.mark.parametrize(
    "tipo,inicio,fim",
    [
        ("ferias", "2025-11-01", "2025-11-10"),
        ("afastamento", "2025-10-01", "2025-11-20"),
        ("afastamento", "2025-12-01", "2025-12-10"),
    ],
)
def test_evento_sem_direito_remunerado_nao_justifica_comissao(
    tipo: str,
    inicio: str,
    fim: str,
) -> None:
    linhas, contexto = exemplo()
    linhas[1]["rastreabilidade"]["linhas_vendas"] = []
    linhas[1]["rastreabilidade"]["eventos_rh"] = ["E"]
    contexto["eventos_rh"] = [evento("E", tipo, "VENDEDOR", inicio, fim)]
    assert finalizar_apuracao(linhas, **contexto)["assercoes"][1]["resultado"] == "violada"


def test_bonus_exige_direito_rastreavel_na_entrada() -> None:
    linhas, contexto = exemplo()
    linhas[1]["rastreabilidade"]["linhas_vendas"] = []
    linhas[1]["rastreabilidade"]["regras_competencia"] = ["BONUS"]
    assert finalizar_apuracao(linhas, **contexto)["assercoes"][1]["resultado"] == "violada"
    contexto["origens_competencia"] = [
        {
            "id": "BONUS",
            "competencia": "2025-11",
            "matricula": "VENDEDOR",
            "tipo": "bonus_final",
            "valor": 100,
        }
    ]
    assert finalizar_apuracao(linhas, **contexto)["assercoes"][1]["resultado"] == "ok"
    contexto["origens_competencia"][0]["matricula"] = "OUTRO"
    assert finalizar_apuracao(linhas, **contexto)["assercoes"][1]["resultado"] == "violada"


def test_soma_por_loja_divergente_falha_sem_recalcular_o_valor_declarado() -> None:
    linhas, contexto = exemplo()
    contexto["por_loja"] = {"1": 109.99}
    desfecho = finalizar_apuracao(linhas, **contexto)["assercoes"][2]
    assert desfecho["resultado"] == "violada"
    assert "2025-11, loja 1" in str(desfecho["detalhe"])


def test_total_igual_com_lojas_trocadas_tambem_falha() -> None:
    linhas, contexto = exemplo()
    contexto["por_loja"] = {"2": 110.0}
    assert finalizar_apuracao(linhas, **contexto)["assercoes"][2]["resultado"] == "violada"


def test_matricula_duplicada_nao_pode_ser_ocultada_pelo_agrupamento() -> None:
    linhas, contexto = exemplo()
    linhas.append(deepcopy(linhas[1]))
    contexto["por_loja"] = {"1": 210.0}
    assert finalizar_apuracao(linhas, **contexto)["assercoes"][2]["resultado"] == "violada"


def test_comissao_zero_sem_venda_e_permitida() -> None:
    resultado = apurar([rh("A")], [], [taxa(0.10)], [], "2025-11")
    assert isinstance(resultado, TabelaApurada)
    assert resultado.resultado_apuracao["status"] == "sucesso"


def test_assercoes_nao_leem_arquivos(monkeypatch: pytest.MonkeyPatch) -> None:
    linhas, contexto = exemplo()

    def proibido(*args: object, **kwargs: object) -> None:
        raise AssertionError("Asserções não podem fazer I/O")

    monkeypatch.setattr("builtins.open", proibido)
    assert finalizar_apuracao(linhas, **contexto)["status"] == "sucesso"
