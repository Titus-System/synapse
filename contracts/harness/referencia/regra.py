"""Regra de referência escrita à mão (T-036), contra o contrato do harness (T-034).

Acréscimo de 0,3% na comissão sobre as vendas da marca 40, na competência de
novembro/2025, para os cargos de venda (loja, balcão e assistente), exceto o
gerente. É o exemplo determinístico de resultado conhecido usado como referência
para a geração de código por LLM (T-054) e para a conferência de cobertura
(T-056). O elemento implementado é declarado em contribuicoes["elemento_ref"].
"""

from __future__ import annotations

import pandas as pd

# valores da regra, embutidos no código gerado
_MARCA_ALVO = 40
_CARGOS_ALVO = (100, 200, 300)
_PERCENTUAL = 0.003
_COMPETENCIA = "2025-11"
_ELEMENTO = "nucleo.percentual"


def aplicar_regra(
    bases: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencias: list[str],
) -> dict[str, pd.DataFrame]:
    """Devolve a apuração simulada e a contribuição por elemento."""
    vendas = bases["vendas"]
    vendas_periodo = vendas[vendas["competencia"].isin(competencias)]
    vendas_alvo = vendas_periodo[
        (vendas_periodo["competencia"] == _COMPETENCIA)
        & (vendas_periodo["cod_marca"] == _MARCA_ALVO)
    ]
    vendas_por_matricula = vendas_alvo.groupby(["matricula", "competencia"], as_index=False)[
        "vlr_venda"
    ].sum()

    simulada = apuracao_base.merge(
        vendas_por_matricula, on=["matricula", "competencia"], how="left"
    )
    simulada["vlr_venda"] = simulada["vlr_venda"].fillna(0.0)
    no_alvo = simulada["cod_cargo"].isin(_CARGOS_ALVO)

    delta = (simulada["vlr_venda"] * _PERCENTUAL).where(no_alvo, 0.0)
    simulada["comissao"] = simulada["comissao"] + delta
    simulada = simulada.drop(columns="vlr_venda")

    contribuicoes = apuracao_base[
        ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]
    ].copy()
    contribuicoes["elemento_ref"] = _ELEMENTO
    contribuicoes["delta"] = delta.to_numpy()
    contribuicoes = contribuicoes[contribuicoes["delta"] != 0.0].reset_index(drop=True)

    return {
        "apuracao_simulada": simulada.reset_index(drop=True),
        "contribuicoes": contribuicoes,
    }
