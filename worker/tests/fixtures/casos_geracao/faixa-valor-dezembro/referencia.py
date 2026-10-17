"""Referência do caso faixa-valor-dezembro (T-245): núcleo mais três faixas de bônus.

Roda apenas no sandbox, como o código gerado. A comissão de quem é das marcas 10 e 20 e dos cargos
100, 200 e 300 passa a ser 2,5% das vendas do mês, e quem tem o total mensal de vendas dentro de
uma faixa ganha o bônus fixo dela, no elemento da faixa.
"""

from __future__ import annotations

import pandas as pd

_MARCAS = (10, 20)
_CARGOS = (100, 200, 300)
_PERCENTUAL = 0.025
# (elemento, limite inferior, limite superior, bônus). Cada faixa vale só no próprio intervalo,
# com os dois limites incluídos: o espaço entre duas faixas seguidas não ganha bônus.
_FAIXAS = (
    ("elem.1", 40000.0, 50000.0, 3500.0),
    ("elem.2", 50001.0, 60000.0, 4000.0),
    ("elem.3", 60001.0, 1000000000.0, 4500.0),
)
_NUCLEO = "nucleo.percentual"

_CHAVE = ["matricula", "competencia"]
_DIMENSOES = ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]


def aplicar_regra(
    bases: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencias: list[str],
) -> dict[str, pd.DataFrame | list[str]]:
    vendas = bases["vendas"]
    # A venda individual é o total mensal de todas as vendas da pessoa, e não cada venda.
    venda_do_mes = (
        vendas[vendas["competencia"].isin(competencias)]
        .groupby(_CHAVE, as_index=False)["vlr_venda"]
        .sum()
    )
    simulada = apuracao_base.merge(venda_do_mes, on=_CHAVE, how="left")
    venda = simulada["vlr_venda"].fillna(0.0)
    no_nucleo = simulada["cod_marca"].isin(_MARCAS) & simulada["cod_cargo"].isin(_CARGOS)

    efeitos_das_faixas = {
        elemento: pd.Series(bonus, index=simulada.index).where(
            no_nucleo & (venda >= inferior) & (venda <= superior), 0.0
        )
        for elemento, inferior, superior, bonus in _FAIXAS
    }
    bonus_das_faixas = sum(efeitos_das_faixas.values(), pd.Series(0.0, index=simulada.index))
    nova_comissao = simulada["comissao"].where(~no_nucleo, venda * _PERCENTUAL + bonus_das_faixas)
    efeito_nucleo = nova_comissao - simulada["comissao"] - bonus_das_faixas
    simulada["comissao"] = nova_comissao
    simulada = simulada.drop(columns="vlr_venda")

    contribuicoes = pd.concat(
        [
            _contribuicao(apuracao_base, _NUCLEO, efeito_nucleo),
            *(
                _contribuicao(apuracao_base, elemento, efeito)
                for elemento, efeito in efeitos_das_faixas.items()
            ),
        ],
        ignore_index=True,
    )

    return {
        "apuracao_simulada": simulada.reset_index(drop=True),
        "contribuicoes": contribuicoes,
        "elementos_implementados": [_NUCLEO, *efeitos_das_faixas],
    }


def _contribuicao(apuracao_base: pd.DataFrame, elemento: str, delta: pd.Series) -> pd.DataFrame:
    linhas = apuracao_base[_DIMENSOES].copy()
    linhas["elemento_ref"] = elemento
    linhas["delta"] = delta.to_numpy()
    return linhas[linhas["delta"] != 0.0]
