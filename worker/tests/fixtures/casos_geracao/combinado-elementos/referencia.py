"""Referência do caso combinado-elementos (T-245): a regra do exemplo do contrato.

Roda apenas no sandbox, como o código gerado. Só em novembro, a comissão de quem é das lojas 13 e
58, da marca 10 e do cargo 100 passa a ser 2% das vendas do mês; dentro desse recorte, a faixa de
40.000 a 50.000 paga R$ 3.500 e a janela de 24 a 30/11 acrescenta 1 ponto percentual às vendas
dela. A exclusão do cargo 150 é declarada e não tem contribuição própria.
"""

from __future__ import annotations

import pandas as pd

_VIGENCIA = ("2025-11", "2025-11")
_LOJAS = (13, 58)
_MARCA = 10
_CARGO = 100
_PERCENTUAL = 0.02
_FAIXA_INFERIOR = 40000.0
_FAIXA_SUPERIOR = 50000.0
_BONUS_FAIXA = 3500.0
_INICIO_JANELA = "2025-11-24"
_FIM_JANELA = "2025-11-30"
_ACRESCIMO_JANELA = 0.01
_CARGOS_EXCLUIDOS = (150,)
_NUCLEO = "nucleo.percentual"
_FAIXA = "elem.1"
_JANELA = "elem.2"
_EXCLUSAO = "elem.3"

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
    na_janela = do_periodo[(data_venda >= _INICIO_JANELA) & (data_venda <= _FIM_JANELA)]
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
    no_nucleo = (
        simulada["competencia"].between(*_VIGENCIA)
        & simulada["cod_loja"].isin(_LOJAS)
        & (simulada["cod_marca"] == _MARCA)
        & (simulada["cod_cargo"] == _CARGO)
        & ~simulada["cod_cargo"].isin(_CARGOS_EXCLUIDOS)
    )
    na_faixa = no_nucleo & (venda >= _FAIXA_INFERIOR) & (venda <= _FAIXA_SUPERIOR)

    efeito_faixa = pd.Series(_BONUS_FAIXA, index=simulada.index).where(na_faixa, 0.0)
    efeito_janela = (venda_janela * _ACRESCIMO_JANELA).where(no_nucleo, 0.0)
    nova_comissao = simulada["comissao"].where(
        ~no_nucleo, venda * _PERCENTUAL + efeito_faixa + efeito_janela
    )
    efeito_nucleo = nova_comissao - simulada["comissao"] - efeito_faixa - efeito_janela
    simulada["comissao"] = nova_comissao
    simulada = simulada.drop(columns=["vlr_venda", "vlr_venda_janela"])

    contribuicoes = pd.concat(
        [
            _contribuicao(apuracao_base, _NUCLEO, efeito_nucleo),
            _contribuicao(apuracao_base, _FAIXA, efeito_faixa),
            _contribuicao(apuracao_base, _JANELA, efeito_janela),
        ],
        ignore_index=True,
    )

    return {
        "apuracao_simulada": simulada.reset_index(drop=True),
        "contribuicoes": contribuicoes,
        # A exclusão tira o cargo 150 do alcance e não gera valor próprio.
        "elementos_implementados": [_NUCLEO, _FAIXA, _JANELA, _EXCLUSAO],
    }


def _contribuicao(apuracao_base: pd.DataFrame, elemento: str, delta: pd.Series) -> pd.DataFrame:
    linhas = apuracao_base[_DIMENSOES].copy()
    linhas["elemento_ref"] = elemento
    linhas["delta"] = delta.to_numpy()
    return linhas[linhas["delta"] != 0.0]
