"""Referência do caso nucleo-controle (T-243): só o núcleo, a regra do exemplo do harness.

Roda apenas no sandbox, como o código gerado. A comissão de quem é da marca 10 no cargo 100
passa a ser 2,5% das vendas do mês; as demais linhas ficam como no baseline.
"""

from __future__ import annotations

import pandas as pd

_MARCA = 10
_CARGO = 100
_PERCENTUAL = 0.025
_NUCLEO = "nucleo.percentual"

_CHAVE = ["matricula", "competencia"]
_DIMENSOES = ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]


def aplicar_regra(
    bases: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencias: list[str],
) -> dict[str, pd.DataFrame | list[str]]:
    vendas = bases["vendas"]
    venda_do_mes = (
        vendas[vendas["competencia"].isin(competencias)]
        .groupby(_CHAVE, as_index=False)["vlr_venda"]
        .sum()
    )
    simulada = apuracao_base.merge(venda_do_mes, on=_CHAVE, how="left")
    venda = simulada["vlr_venda"].fillna(0.0)
    no_alvo = (simulada["cod_marca"] == _MARCA) & (simulada["cod_cargo"] == _CARGO)

    nova_comissao = simulada["comissao"].where(~no_alvo, venda * _PERCENTUAL)
    efeito_nucleo = nova_comissao - simulada["comissao"]
    simulada["comissao"] = nova_comissao
    simulada = simulada.drop(columns="vlr_venda")

    contribuicoes = apuracao_base[_DIMENSOES].copy()
    contribuicoes["elemento_ref"] = _NUCLEO
    contribuicoes["delta"] = efeito_nucleo.to_numpy()
    contribuicoes = contribuicoes[contribuicoes["delta"] != 0.0].reset_index(drop=True)

    return {
        "apuracao_simulada": simulada.reset_index(drop=True),
        "contribuicoes": contribuicoes,
        "elementos_implementados": [_NUCLEO],
    }
