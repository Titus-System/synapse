"""Referência do caso janela-datas-black-friday (T-245): núcleo mais a janela da Black Friday.

Roda apenas no sandbox, como o código gerado. A comissão de quem é dos cargos 100, 200 e 300 passa
a ser 2,5% das vendas do mês, e as vendas com data_venda de 24 a 30/11 ganham mais 1 ponto
percentual sobre o valor delas.
"""

from __future__ import annotations

import pandas as pd

_CARGOS = (100, 200, 300)
_PERCENTUAL = 0.025
_INICIO = "2025-11-24"
_FIM = "2025-11-30"
_ACRESCIMO = 0.01
_NUCLEO = "nucleo.percentual"
_JANELA = "elem.1"

_CHAVE = ["matricula", "competencia"]
_DIMENSOES = ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]


def aplicar_regra(
    bases: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencias: list[str],
) -> dict[str, pd.DataFrame | list[str]]:
    vendas = bases["vendas"]
    do_periodo = vendas[vendas["competencia"].isin(competencias)]
    venda_do_mes = do_periodo.groupby(_CHAVE, as_index=False)["vlr_venda"].sum()
    # A venda que só tem a referência mensal chega com data_venda nula e não cai em nenhuma
    # janela; data_venda é AAAA-MM-DD, então a ordem do texto é a ordem das datas.
    data_venda = do_periodo["data_venda"].fillna("")
    na_janela = do_periodo[(data_venda >= _INICIO) & (data_venda <= _FIM)]
    venda_na_janela = (
        na_janela.groupby(_CHAVE, as_index=False)["vlr_venda"]
        .sum()
        .rename(columns={"vlr_venda": "vlr_venda_janela"})
    )
    simulada = apuracao_base.merge(venda_do_mes, on=_CHAVE, how="left").merge(
        venda_na_janela, on=_CHAVE, how="left"
    )
    venda = simulada["vlr_venda"].fillna(0.0)
    venda_janela = simulada["vlr_venda_janela"].fillna(0.0)
    no_nucleo = simulada["cod_cargo"].isin(_CARGOS)

    efeito_janela = (venda_janela * _ACRESCIMO).where(no_nucleo, 0.0)
    nova_comissao = simulada["comissao"].where(~no_nucleo, venda * _PERCENTUAL + efeito_janela)
    efeito_nucleo = nova_comissao - simulada["comissao"] - efeito_janela
    simulada["comissao"] = nova_comissao
    simulada = simulada.drop(columns=["vlr_venda", "vlr_venda_janela"])

    contribuicoes = pd.concat(
        [
            _contribuicao(apuracao_base, _NUCLEO, efeito_nucleo),
            _contribuicao(apuracao_base, _JANELA, efeito_janela),
        ],
        ignore_index=True,
    )

    return {
        "apuracao_simulada": simulada.reset_index(drop=True),
        "contribuicoes": contribuicoes,
        "elementos_implementados": [_NUCLEO, _JANELA],
    }


def _contribuicao(apuracao_base: pd.DataFrame, elemento: str, delta: pd.Series) -> pd.DataFrame:
    linhas = apuracao_base[_DIMENSOES].copy()
    linhas["elemento_ref"] = elemento
    linhas["delta"] = delta.to_numpy()
    return linhas[linhas["delta"] != 0.0]
