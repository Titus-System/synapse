import json
from pathlib import Path
from typing import Any

import pytest

from app.sandbox.regras_base import RuidoDadosWarning, apurar


class DataFrameFalso:
    def __init__(self, linhas: list[dict[str, object]]) -> None:
        self.linhas = linhas

    def to_dict(self, orient: str = "dict") -> object:
        assert orient == "records"
        return [linha.copy() for linha in self.linhas]


def rh(
    matricula: str,
    *,
    competencia: str = "2025-11",
    cod_marca: int = 10,
    cod_loja: int = 1,
    cod_cargo: int = 100,
    data_admiss: str = "2020-01-01",
    data_demiss: str | None = None,
    descr_cargo: str = "VENDEDOR LOJA",
) -> dict[str, object]:
    return {
        "competencia": competencia,
        "data_ref": f"{competencia}-01",
        "cod_marca": cod_marca,
        "descr_marca": "PRETO",
        "cod_loja": cod_loja,
        "descr_loja": f"LOJA-{cod_loja}",
        "matricula": matricula,
        "data_admiss": data_admiss,
        "data_demiss": data_demiss,
        "cod_cargo": cod_cargo,
        "descr_cargo": descr_cargo,
    }


def venda(
    matricula: str,
    valor: float,
    *,
    competencia: str = "2025-11",
    cod_marca: int = 10,
    cod_loja: int = 1,
) -> dict[str, object]:
    return {
        "competencia": competencia,
        "data_ref": f"{competencia}-01",
        "data_venda": None,
        "cod_marca": cod_marca,
        "descr_marca": "PRETO",
        "cod_loja": cod_loja,
        "descr_loja": f"LOJA-{cod_loja}",
        "matricula": matricula,
        "vlr_venda": valor,
    }


def taxa(
    percentual: float,
    *,
    competencia: str = "2025-11",
    cod_marca: int = 10,
    cod_cargo: int = 100,
) -> dict[str, object]:
    return {
        "competencia": competencia,
        "cod_marca": cod_marca,
        "descr_marca": "PRETO",
        "cod_cargo": cod_cargo,
        "descr_cargo": "GERENTE DE LOJA" if cod_cargo == 150 else "VENDEDOR LOJA",
        "percentual_comissao": percentual,
    }


def evento(
    identificador: str,
    tipo: str,
    matricula: str,
    inicio: str | None,
    fim: str | None,
    *,
    competencia_origem: str = "2025-11",
    detalhes: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": identificador,
        "tipo": tipo,
        "matricula": matricula,
        "competencia_origem": competencia_origem,
        "data_inicio": inicio,
        "data_fim": fim,
        "detalhes": detalhes,
    }


def por_matricula(resultado: object, matricula: str) -> dict[str, Any]:
    if isinstance(resultado, DataFrameFalso):
        linhas = resultado.linhas
    else:
        assert isinstance(resultado, list)
        linhas = resultado
    return next(linha for linha in linhas if linha["matricula"] == matricula)


def test_regra_geral_reproduz_exemplo_de_percentual_sobre_venda() -> None:
    resultado = apurar(
        [rh("MATRIC-422")],
        [venda("MATRIC-422", 32400)],
        [taxa(0.025)],
        [],
        "2025-11",
    )

    linha = por_matricula(resultado, "MATRIC-422")
    assert linha["base_calculo"] == 32400.0
    assert linha["comissao"] == 810.0


def test_gerente_usa_venda_total_da_loja_incluindo_a_propria_venda() -> None:
    resultado = apurar(
        [
            rh("GERENTE", cod_cargo=150, descr_cargo="GERENTE QUIOSQUE"),
            rh("VENDEDOR-A"),
            rh("VENDEDOR-B"),
        ],
        [
            venda("GERENTE", 5000),
            venda("VENDEDOR-A", 10000),
            venda("VENDEDOR-B", 20000),
        ],
        [taxa(0.01, cod_cargo=150), taxa(0.025)],
        [],
        "2025-11",
    )

    gerente = por_matricula(resultado, "GERENTE")
    assert gerente["base_calculo"] == 35000.0
    assert gerente["comissao"] == 350.0


def test_rastreabilidade_gerente_inclui_todas_as_vendas_da_loja() -> None:
    resultado = apurar(
        [
            rh("GERENTE", cod_cargo=150, descr_cargo="GERENTE DE LOJA"),
            rh("VENDEDOR-A"),
            rh("VENDEDOR-B"),
        ],
        [
            venda("GERENTE", 5000),
            venda("VENDEDOR-A", 10000),
            venda("VENDEDOR-B", 20000),
        ],
        [taxa(0.01, cod_cargo=150), taxa(0.025)],
        [],
        "2025-11",
    )

    gerente = por_matricula(resultado, "GERENTE")
    vendedor = por_matricula(resultado, "VENDEDOR-A")
    assert gerente["base_calculo"] == 35000.0
    assert gerente["rastreabilidade"]["linhas_vendas"] == [1, 2, 3]
    assert vendedor["rastreabilidade"]["linhas_vendas"] == [2]


def test_admissao_em_10_de_outubro_usa_21_de_31_dias() -> None:
    resultado = apurar(
        [rh("NOVO", competencia="2025-10", data_admiss="2025-10-10")],
        [venda("NOVO", 31000, competencia="2025-10")],
        [taxa(0.10, competencia="2025-10")],
        [],
        "2025-10",
    )

    linha = por_matricula(resultado, "NOVO")
    assert linha["base_calculo"] == 21000.0
    assert linha["comissao"] == 2100.0


def test_demissao_em_10_de_novembro_usa_10_de_30_dias() -> None:
    resultado = apurar(
        [rh("DEMITIDO", data_demiss="2025-11-10")],
        [venda("DEMITIDO", 30000)],
        [taxa(0.10)],
        [],
        "2025-11",
    )

    linha = por_matricula(resultado, "DEMITIDO")
    assert linha["base_calculo"] == 10000.0
    assert linha["comissao"] == 1000.0


def test_admissao_e_demissao_na_mesma_competencia_usam_intervalo_trabalhado() -> None:
    resultado = apurar(
        [
            rh(
                "CURTO",
                competencia="2025-09",
                data_admiss="2025-09-08",
                data_demiss="2025-09-15",
            )
        ],
        [venda("CURTO", 30000, competencia="2025-09")],
        [taxa(0.10, competencia="2025-09")],
        [],
        "2025-09",
    )

    linha = por_matricula(resultado, "CURTO")
    assert linha["base_calculo"] == 7000.0
    assert linha["comissao"] == 700.0


def test_afastamento_de_10_dias_reproduz_base_adicional_de_10_mil() -> None:
    resultado = apurar(
        [rh("ATESTADO-10")],
        [venda("ATESTADO-10", 20000)],
        [taxa(0.025)],
        [evento("EVT-10", "afastamento", "ATESTADO-10", "2025-11-01", "2025-11-10")],
        "2025-11",
    )

    linha = por_matricula(resultado, "ATESTADO-10")
    assert linha["base_calculo"] == 30000.0
    assert linha["base_calculo"] - linha["rastreabilidade"]["base_original"] == 10000.0
    assert linha["comissao"] == 3500.0
    assert linha["rastreabilidade"]["afastamento"] == {
        "dias_total": 10,
        "dias_remunerados": 10,
        "piso_aplicado": True,
    }


def test_afastamento_de_20_dias_reproduz_base_adicional_de_12_mil() -> None:
    resultado = apurar(
        [rh("ATESTADO-20")],
        [venda("ATESTADO-20", 8000)],
        [taxa(0.025)],
        [evento("EVT-20", "afastamento", "ATESTADO-20", "2025-11-01", "2025-11-20")],
        "2025-11",
    )

    linha = por_matricula(resultado, "ATESTADO-20")
    assert linha["base_calculo"] == 20000.0
    assert linha["base_calculo"] - linha["rastreabilidade"]["base_original"] == 12000.0
    assert linha["comissao"] == 3500.0
    assert linha["rastreabilidade"]["afastamento"] == {
        "dias_total": 20,
        "dias_remunerados": 15,
        "piso_aplicado": True,
    }


def test_afastamento_acima_de_15_dias_limita_a_projecao_a_15_dias() -> None:
    resultado = apurar(
        [rh("ATESTADO-ALTO")],
        [venda("ATESTADO-ALTO", 100000)],
        [taxa(0.10)],
        [
            evento(
                "EVT-20-ALTO",
                "afastamento",
                "ATESTADO-ALTO",
                "2025-11-01",
                "2025-11-20",
            )
        ],
        "2025-11",
    )

    linha = por_matricula(resultado, "ATESTADO-ALTO")
    assert linha["base_calculo"] == 250000.0
    assert linha["comissao"] == 25000.0


def test_afastamento_gerente_usa_total_loja_e_piso() -> None:
    resultado = apurar(
        [
            rh("GERENTE-AFASTADO", cod_cargo=150, descr_cargo="GERENTE DE LOJA"),
            rh("VENDEDOR"),
        ],
        [
            venda("GERENTE-AFASTADO", 5000),
            venda("VENDEDOR", 15000),
        ],
        [taxa(0.01, cod_cargo=150), taxa(0.025)],
        [
            evento(
                "EVT-GERENTE-AFASTADO",
                "afastamento",
                "GERENTE-AFASTADO",
                "2025-11-01",
                "2025-11-10",
            )
        ],
        "2025-11",
    )

    gerente = por_matricula(resultado, "GERENTE-AFASTADO")
    assert gerente["rastreabilidade"]["base_original"] == 20000.0
    assert gerente["base_calculo"] == 30000.0
    assert gerente["comissao"] == 3500.0
    assert gerente["rastreabilidade"]["afastamento"] == {
        "dias_total": 10,
        "dias_remunerados": 10,
        "piso_aplicado": True,
    }


def test_ferias_reduzem_a_apuracao_aos_dias_fora_do_gozo() -> None:
    resultado = apurar(
        [rh("FERIAS", competencia="2025-10")],
        [venda("FERIAS", 31000, competencia="2025-10")],
        [taxa(0.10, competencia="2025-10")],
        [
            evento(
                "EVT-FERIAS",
                "ferias",
                "FERIAS",
                "2025-10-01",
                "2025-10-10",
                competencia_origem="2025-10",
            )
        ],
        "2025-10",
    )

    linha = por_matricula(resultado, "FERIAS")
    assert linha["base_calculo"] == 21000.0
    assert linha["comissao"] == 2100.0


def test_ferias_do_gerente_usam_venda_total_da_loja_com_proporcionalidade() -> None:
    resultado = apurar(
        [
            rh(
                "GERENTE-FERIAS",
                competencia="2025-10",
                cod_cargo=150,
                descr_cargo="GERENTE DE LOJA",
            ),
            rh("VENDEDOR", competencia="2025-10"),
        ],
        [
            venda("GERENTE-FERIAS", 1000, competencia="2025-10"),
            venda("VENDEDOR", 30000, competencia="2025-10"),
        ],
        [taxa(0.10, competencia="2025-10", cod_cargo=150), taxa(0.10, competencia="2025-10")],
        [
            evento(
                "EVT-GERENTE-FERIAS",
                "ferias",
                "GERENTE-FERIAS",
                "2025-10-01",
                "2025-10-10",
                competencia_origem="2025-10",
            )
        ],
        "2025-10",
    )

    gerente = por_matricula(resultado, "GERENTE-FERIAS")
    assert gerente["base_calculo"] == 21000.0
    assert gerente["comissao"] == 2100.0


def test_afastamento_que_atravessa_mes_respeita_limite_global_de_15_dias() -> None:
    afastamento = evento(
        "EVT-CRUZADO",
        "afastamento",
        "CRUZADO",
        "2025-08-18",
        "2025-09-08",
        competencia_origem="2025-08",
    )
    agosto = apurar(
        [rh("CRUZADO", competencia="2025-08")],
        [venda("CRUZADO", 17000, competencia="2025-08")],
        [taxa(0.025, competencia="2025-08")],
        [afastamento],
        "2025-08",
    )
    setembro = apurar(
        [rh("CRUZADO", competencia="2025-09")],
        [venda("CRUZADO", 22000, competencia="2025-09")],
        [taxa(0.025, competencia="2025-09")],
        [afastamento],
        "2025-09",
    )

    linha_agosto = por_matricula(agosto, "CRUZADO")
    linha_setembro = por_matricula(setembro, "CRUZADO")
    assert linha_agosto["base_calculo"] == 31000.0
    assert linha_agosto["rastreabilidade"]["afastamento"]["dias_remunerados"] == 14
    assert linha_setembro["base_calculo"] == 23000.0
    assert linha_setembro["rastreabilidade"]["afastamento"]["dias_remunerados"] == 1


def test_data_fim_evento_e_inclusiva_conforme_t028() -> None:
    resultado = apurar(
        [rh("MATRIC-58", competencia="2025-07")],
        [venda("MATRIC-58", 15000, competencia="2025-07")],
        [taxa(0.10, competencia="2025-07")],
        [
            evento(
                "EVT-MATRIC-58",
                "afastamento",
                "MATRIC-58",
                "2025-07-10",
                "2025-07-25",
                competencia_origem="2025-07",
            )
        ],
        "2025-07",
    )

    linha = por_matricula(resultado, "MATRIC-58")
    assert linha["rastreabilidade"]["afastamento"] == {
        "dias_total": 16,
        "dias_remunerados": 15,
        "piso_aplicado": True,
    }
    assert "5f" in linha["rastreabilidade"]["regras_aplicadas"]


def test_licenca_maternidade_e_tratada_como_afastamento_comum() -> None:
    licenca = evento(
        "EVT-MATERNIDADE",
        "licenca_maternidade",
        "MAE",
        "2025-10-01",
        None,
        competencia_origem="2025-10",
        detalhes={"duracao_legal_dias": 120, "data_fim_estimada": "2026-01-29"},
    )

    outubro = apurar(
        [rh("MAE", competencia="2025-10")],
        [],
        [taxa(0.025, competencia="2025-10")],
        [licenca],
        "2025-10",
    )
    novembro = apurar(
        [rh("MAE")],
        [venda("MAE", 30000)],
        [taxa(0.025)],
        [licenca],
        "2025-11",
    )

    linha_outubro = por_matricula(outubro, "MAE")
    linha_novembro = por_matricula(novembro, "MAE")
    assert linha_outubro["base_calculo"] == 0.0
    assert linha_outubro["comissao"] == 3500.0
    assert linha_outubro["rastreabilidade"]["afastamento"]["dias_remunerados"] == 15
    assert linha_novembro["base_calculo"] == 0.0
    assert linha_novembro["comissao"] == 0.0
    assert linha_novembro["rastreabilidade"]["afastamento"]["dias_remunerados"] == 0


def test_correcao_cadastral_de_demissao_e_aplicada_em_memoria() -> None:
    correcao = evento(
        "EVT-CORRECAO",
        "correcao_cadastral",
        "MATRIC-62",
        None,
        None,
        competencia_origem="2025-09",
        detalhes={
            "campo": "Data_Demiss",
            "valor_anterior": "2025-09-30",
            "valor_novo": "2025-09-15",
        },
    )
    setembro = apurar(
        [rh("MATRIC-62", competencia="2025-09")],
        [venda("MATRIC-62", 30000, competencia="2025-09")],
        [taxa(0.10, competencia="2025-09")],
        [correcao],
        "2025-09",
    )
    outubro = apurar(
        [rh("MATRIC-62", competencia="2025-10")],
        [venda("MATRIC-62", 30000, competencia="2025-10")],
        [taxa(0.10, competencia="2025-10")],
        [correcao],
        "2025-10",
    )

    assert por_matricula(setembro, "MATRIC-62")["comissao"] == 1500.0
    assert outubro == []


def test_evento_demissao_atual_da_t028_corrige_data_em_memoria() -> None:
    evento_demissao = evento(
        "EVT-DEMISSAO",
        "demissao",
        "MATRIC-62",
        "2025-09-15",
        None,
        competencia_origem="2025-09",
    )
    resultado = apurar(
        [rh("MATRIC-62", competencia="2025-09")],
        [venda("MATRIC-62", 30000, competencia="2025-09")],
        [taxa(0.10, competencia="2025-09")],
        [evento_demissao],
        "2025-09",
    )

    assert por_matricula(resultado, "MATRIC-62")["comissao"] == 1500.0


def test_venda_sem_rh_e_excluida_com_aviso_explicito() -> None:
    with pytest.warns(RuidoDadosWarning, match="ORFA"):
        resultado = apurar(
            [rh("GERENTE", cod_cargo=150, descr_cargo="GERENTE DE LOJA")],
            [venda("GERENTE", 10000), venda("ORFA", 90000)],
            [taxa(0.01, cod_cargo=150)],
            [],
            "2025-11",
        )

    gerente = por_matricula(resultado, "GERENTE")
    assert gerente["base_calculo"] == 10000.0


def test_comissao_de_multiplas_marcas_usa_a_taxa_de_cada_marca() -> None:
    resultado = apurar(
        [rh("MULTIMARCA")],
        [
            venda("MULTIMARCA", 10000, cod_marca=10),
            venda("MULTIMARCA", 10000, cod_marca=30),
        ],
        [taxa(0.025, cod_marca=10), taxa(0.02, cod_marca=30)],
        [],
        "2025-11",
    )

    linha = por_matricula(resultado, "MULTIMARCA")
    assert linha["base_calculo"] == 20000.0
    assert linha["comissao"] == 450.0


def test_saida_preserva_tipo_dataframe_like_sem_depender_de_pandas() -> None:
    resultado = apurar(
        DataFrameFalso([rh("DF")]),
        DataFrameFalso([venda("DF", 1000)]),
        DataFrameFalso([taxa(0.025)]),
        DataFrameFalso([]),
        "2025-11",
    )

    assert isinstance(resultado, DataFrameFalso)
    assert resultado.linhas[0]["matricula"] == "DF"


def test_dataset_canonico_publicado_e_consumido_sem_xlsx() -> None:
    data_dir = Path(__file__).resolve().parents[3] / "sandbox" / "data" / "domrock"

    def ler_jsonl(nome: str) -> list[dict[str, object]]:
        with (data_dir / nome).open(encoding="utf-8") as arquivo:
            return [json.loads(linha) for linha in arquivo if linha.strip()]

    resultado = apurar(
        ler_jsonl("rh.jsonl"),
        ler_jsonl("vendas.jsonl"),
        ler_jsonl("comissoes.jsonl"),
        [],
        "2025-08",
    )

    assert isinstance(resultado, list)
    assert resultado
    assert {"matricula", "loja", "cargo", "base_calculo", "comissao", "rastreabilidade"} <= set(
        resultado[0]
    )
