"""Referência de taxas por cargo, executada exclusivamente no sandbox."""

from __future__ import annotations

import pandas as pd

_TAXAS = {100: 0.03, 150: 0.05}
_MARCA = 10
_NUCLEO = "nucleo.taxas_por_cargo"
_CHAVE = ["matricula", "competencia"]
_DIMENSOES = ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]


def aplicar_regra(
    bases: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencias: list[str],
) -> dict[str, pd.DataFrame | list[str]]:
    vendas = bases["vendas"]
    vendas = vendas[vendas["competencia"].isin(competencias)]
    individual = vendas.groupby(_CHAVE, as_index=False)["vlr_venda"].sum()
    do_quadro = vendas.merge(apuracao_base[_CHAVE], on=_CHAVE, how="inner")
    da_loja = do_quadro.groupby(["cod_loja", "competencia"], as_index=False)["vlr_venda"].sum()
    da_loja = da_loja.rename(columns={"vlr_venda": "venda_loja"})
    simulada = apuracao_base.merge(individual, on=_CHAVE, how="left").merge(
        da_loja, on=["cod_loja", "competencia"], how="left"
    )
    venda = (
        simulada["vlr_venda"]
        .fillna(0.0)
        .where(simulada["cod_cargo"] != 150, simulada["venda_loja"].fillna(0.0))
    )
    taxas = simulada["cod_cargo"].map(_TAXAS)
    alvo = (simulada["cod_marca"] == _MARCA) & taxas.notna()
    nova = simulada["comissao"].where(~alvo, venda * taxas)
    contribuicoes = simulada[_DIMENSOES].copy()
    contribuicoes["elemento_ref"] = _NUCLEO
    contribuicoes["delta"] = nova - simulada["comissao"]
    simulada["comissao"] = nova
    return {
        "apuracao_simulada": simulada.drop(columns=["vlr_venda", "venda_loja"]),
        "contribuicoes": contribuicoes[contribuicoes["delta"] != 0.0].reset_index(drop=True),
        "elementos_implementados": [_NUCLEO],
    }
