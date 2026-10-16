"""Referência do caso exclusao-gerente (T-245): núcleo mais a exclusão dos gerentes.

Roda apenas no sandbox, como o código gerado. A comissão de quem é da marca 30 passa a ser 2,5%
das vendas do mês, exceto para o cargo 150, que a exclusão deixa como no baseline. A exclusão é
declarada e não tem contribuição própria.
"""

from __future__ import annotations

import pandas as pd

_MARCA = 30
_PERCENTUAL = 0.025
_CARGOS_EXCLUIDOS = (150,)
_NUCLEO = "nucleo.percentual"
_EXCLUSAO = "elem.1"

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
    no_alcance = (simulada["cod_marca"] == _MARCA) & ~simulada["cod_cargo"].isin(_CARGOS_EXCLUIDOS)

    nova_comissao = simulada["comissao"].where(~no_alcance, venda * _PERCENTUAL)
    efeito_nucleo = nova_comissao - simulada["comissao"]
    simulada["comissao"] = nova_comissao
    simulada = simulada.drop(columns="vlr_venda")

    return {
        "apuracao_simulada": simulada.reset_index(drop=True),
        "contribuicoes": _contribuicao(apuracao_base, _NUCLEO, efeito_nucleo).reset_index(
            drop=True
        ),
        # A exclusão tira os gerentes do alcance e não gera valor próprio.
        "elementos_implementados": [_NUCLEO, _EXCLUSAO],
    }


def _contribuicao(apuracao_base: pd.DataFrame, elemento: str, delta: pd.Series) -> pd.DataFrame:
    linhas = apuracao_base[_DIMENSOES].copy()
    linhas["elemento_ref"] = elemento
    linhas["delta"] = delta.to_numpy()
    return linhas[linhas["delta"] != 0.0]
