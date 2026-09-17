"""Exemplo de código gerado contra o contrato do harness (T-034).

Regra só de núcleo: aplica 2,5% de comissão nas vendas da marca 10 no cargo
100, em todo o período processado (sem vigência restrita, a regra vale para
todas as competências do job - regra-nucleo.schema.json). A função é pura
(DataFrames entram, resultado sai), não lê arquivo e recebe as competências
do período por parâmetro. O elemento implementado é declarado em
contribuicoes["elemento_ref"].
"""

from __future__ import annotations

import pandas as pd

# valores da regra, embutidos no código gerado
_MARCA_ALVO = 10
_CARGO_ALVO = 100
_PERCENTUAL = 0.025
_ELEMENTO = "nucleo.percentual"


def aplicar_regra(
    bases: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencias: list[str],
) -> dict[str, pd.DataFrame]:
    """Devolve a apuração simulada e a contribuição por elemento."""
    vendas = bases["vendas"]
    vendas_periodo = vendas[vendas["competencia"].isin(competencias)]
    vendas_por_matricula_competencia = vendas_periodo.groupby(
        ["matricula", "competencia"], as_index=False
    )["vlr_venda"].sum()

    simulada = apuracao_base.merge(
        vendas_por_matricula_competencia, on=["matricula", "competencia"], how="left"
    )
    simulada["vlr_venda"] = simulada["vlr_venda"].fillna(0.0)
    no_alvo = (simulada["cod_marca"] == _MARCA_ALVO) & (simulada["cod_cargo"] == _CARGO_ALVO)

    nova_comissao = simulada["comissao"].where(~no_alvo, simulada["vlr_venda"] * _PERCENTUAL)
    delta = nova_comissao - simulada["comissao"]
    simulada["comissao"] = nova_comissao
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
