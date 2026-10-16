"""Referência do caso bonus-fixo-lista-e-filtro (T-245): núcleo mais dois bônus fixos.

Roda apenas no sandbox, como o código gerado. A comissão de quem é das marcas 10 e 20 e dos cargos
100, 200 e 300 passa a ser 2,5% das vendas do mês. Dentro desse recorte, elem.1 paga R$ 500 às
matrículas da lista e elem.2 paga R$ 1.000 a quem é do cargo 100 e foi admitido até 10/10/2025, uma
vez por competência em que a pessoa está no baseline.
"""

from __future__ import annotations

import pandas as pd

_MARCAS = (10, 20)
_CARGOS = (100, 200, 300)
_PERCENTUAL = 0.025
_LISTA = (
    "MATRIC-134",
    "MATRIC-135",
    "MATRIC-14",
    "MATRIC-141",
    "MATRIC-143",
    "MATRIC-144",
    "MATRIC-147",
    "MATRIC-148",
    "MATRIC-133",
)
_VALOR_LISTA = 500.0
_CARGO_DO_FILTRO = 100
_ADMITIDO_ATE = "2025-10-10"
_VALOR_FILTRO = 1000.0
_NUCLEO = "nucleo.percentual"
_BONUS_LISTA = "elem.1"
_BONUS_FILTRO = "elem.2"

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
    # As linhas de apuracao_base são o quadro de cada competência: uma matrícula fora dele não
    # tem linha, e por isso não recebe bônus nela.
    simulada = apuracao_base.merge(venda_do_mes, on=_CHAVE, how="left").merge(
        admissao, on=_CHAVE, how="left", validate="one_to_one"
    )
    venda = simulada["vlr_venda"].fillna(0.0)
    no_nucleo = simulada["cod_marca"].isin(_MARCAS) & simulada["cod_cargo"].isin(_CARGOS)
    na_lista = no_nucleo & simulada["matricula"].isin(_LISTA)
    # data_admiss é AAAA-MM-DD, então a ordem do texto é a ordem das datas.
    no_filtro = (
        no_nucleo
        & (simulada["cod_cargo"] == _CARGO_DO_FILTRO)
        & (simulada["data_admiss"] <= _ADMITIDO_ATE)
    )

    efeito_lista = pd.Series(_VALOR_LISTA, index=simulada.index).where(na_lista, 0.0)
    efeito_filtro = pd.Series(_VALOR_FILTRO, index=simulada.index).where(no_filtro, 0.0)
    nova_comissao = simulada["comissao"].where(
        ~no_nucleo, venda * _PERCENTUAL + efeito_lista + efeito_filtro
    )
    efeito_nucleo = nova_comissao - simulada["comissao"] - efeito_lista - efeito_filtro
    simulada["comissao"] = nova_comissao
    simulada = simulada.drop(columns=["vlr_venda", "data_admiss"])

    contribuicoes = pd.concat(
        [
            _contribuicao(apuracao_base, _NUCLEO, efeito_nucleo),
            _contribuicao(apuracao_base, _BONUS_LISTA, efeito_lista),
            _contribuicao(apuracao_base, _BONUS_FILTRO, efeito_filtro),
        ],
        ignore_index=True,
    )

    return {
        "apuracao_simulada": simulada.reset_index(drop=True),
        "contribuicoes": contribuicoes,
        "elementos_implementados": [_NUCLEO, _BONUS_LISTA, _BONUS_FILTRO],
    }


def _contribuicao(apuracao_base: pd.DataFrame, elemento: str, delta: pd.Series) -> pd.DataFrame:
    linhas = apuracao_base[_DIMENSOES].copy()
    linhas["elemento_ref"] = elemento
    linhas["delta"] = delta.to_numpy()
    return linhas[linhas["delta"] != 0.0]
