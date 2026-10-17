"""Referência do caso generico-admissao (T-243): núcleo mais um acréscimo por admissão.

Roda apenas no sandbox, como o código gerado. A comissão de quem é da marca 10 no cargo 100
passa a ser 2,5% das vendas do mês, e quem desse recorte foi admitido antes de 01/01/2020
ganha mais 1 ponto percentual. A diferença de cada pessoa se divide entre os dois elementos:
elem.1 fica com o acréscimo, e nucleo.percentual com o restante.
"""

from __future__ import annotations

import pandas as pd

_MARCA = 10
_CARGO = 100
_PERCENTUAL = 0.025
_ACRESCIMO = 0.01
_ADMITIDO_ANTES_DE = "2020-01-01"
_NUCLEO = "nucleo.percentual"
_ADMISSAO = "elem.1"

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
    admissao = bases["rh"][[*_CHAVE, "data_admiss"]]
    simulada = apuracao_base.merge(venda_do_mes, on=_CHAVE, how="left").merge(
        admissao, on=_CHAVE, how="left", validate="one_to_one"
    )
    venda = simulada["vlr_venda"].fillna(0.0)
    no_alvo = (simulada["cod_marca"] == _MARCA) & (simulada["cod_cargo"] == _CARGO)
    # data_admiss é AAAA-MM-DD, então a ordem do texto é a ordem das datas.
    admitido_antes = no_alvo & (simulada["data_admiss"] < _ADMITIDO_ANTES_DE)

    percentual = pd.Series(_PERCENTUAL, index=simulada.index).where(
        ~admitido_antes, _PERCENTUAL + _ACRESCIMO
    )
    nova_comissao = simulada["comissao"].where(~no_alvo, venda * percentual)
    efeito_admissao = (venda * _ACRESCIMO).where(admitido_antes, 0.0)
    efeito_nucleo = nova_comissao - simulada["comissao"] - efeito_admissao
    simulada["comissao"] = nova_comissao
    simulada = simulada.drop(columns=["vlr_venda", "data_admiss"])

    contribuicoes = pd.concat(
        [
            _contribuicao(apuracao_base, _NUCLEO, efeito_nucleo),
            _contribuicao(apuracao_base, _ADMISSAO, efeito_admissao),
        ],
        ignore_index=True,
    )

    return {
        "apuracao_simulada": simulada.reset_index(drop=True),
        "contribuicoes": contribuicoes,
        "elementos_implementados": [_NUCLEO, _ADMISSAO],
    }


def _contribuicao(apuracao_base: pd.DataFrame, elemento: str, delta: pd.Series) -> pd.DataFrame:
    linhas = apuracao_base[_DIMENSOES].copy()
    linhas["elemento_ref"] = elemento
    linhas["delta"] = delta.to_numpy()
    return linhas[linhas["delta"] != 0.0]
