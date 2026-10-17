"""Referência do caso condicao-limiar-loja (T-245): núcleo liberado pela venda da loja.

Roda apenas no sandbox, como o código gerado. A comissão de quem é dos cargos 100, 200 e 300 passa
a ser 3% das vendas do mês, mas só nas lojas que venderam ao menos R$ 50.000 naquela competência;
nas demais, fica como no baseline. A condição é declarada e não tem contribuição própria.
"""

from __future__ import annotations

import pandas as pd

_CARGOS = (100, 200, 300)
_PERCENTUAL = 0.03
_LIMIAR = 50000.0
_NUCLEO = "nucleo.percentual"
_CONDICAO = "elem.1"

_CHAVE = ["matricula", "competencia"]
_LOJA_NO_MES = ["cod_loja", "competencia"]
_DIMENSOES = ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]


def aplicar_regra(
    bases: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencias: list[str],
) -> dict[str, pd.DataFrame | list[str]]:
    vendas = bases["vendas"]
    do_periodo = vendas[vendas["competencia"].isin(competencias)]
    venda_do_mes = do_periodo.groupby(_CHAVE, as_index=False)["vlr_venda"].sum()
    # A venda da loja soma as vendas pelo cod_loja delas, como as regras base, mês a mês; a
    # pessoa é comparada pela loja da sua linha no baseline.
    venda_da_loja = (
        do_periodo.groupby(_LOJA_NO_MES, as_index=False)["vlr_venda"]
        .sum()
        .rename(columns={"vlr_venda": "venda_da_loja"})
    )
    simulada = apuracao_base.merge(venda_do_mes, on=_CHAVE, how="left").merge(
        venda_da_loja, on=_LOJA_NO_MES, how="left"
    )
    venda = simulada["vlr_venda"].fillna(0.0)
    no_nucleo = simulada["cod_cargo"].isin(_CARGOS)
    liberada = no_nucleo & (simulada["venda_da_loja"].fillna(0.0) >= _LIMIAR)

    nova_comissao = simulada["comissao"].where(~liberada, venda * _PERCENTUAL)
    efeito_nucleo = nova_comissao - simulada["comissao"]
    simulada["comissao"] = nova_comissao
    simulada = simulada.drop(columns=["vlr_venda", "venda_da_loja"])

    return {
        "apuracao_simulada": simulada.reset_index(drop=True),
        "contribuicoes": _contribuicao(apuracao_base, _NUCLEO, efeito_nucleo).reset_index(
            drop=True
        ),
        # A condição decide onde o núcleo vale e não gera valor próprio.
        "elementos_implementados": [_NUCLEO, _CONDICAO],
    }


def _contribuicao(apuracao_base: pd.DataFrame, elemento: str, delta: pd.Series) -> pd.DataFrame:
    linhas = apuracao_base[_DIMENSOES].copy()
    linhas["elemento_ref"] = elemento
    linhas["delta"] = delta.to_numpy()
    return linhas[linhas["delta"] != 0.0]
