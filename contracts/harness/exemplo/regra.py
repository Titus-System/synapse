"""Exemplo de código gerado contra o contrato do harness (T-034).

Regra só de núcleo: aplica 2,5% de comissão nas vendas da marca 10 no cargo
100. A função é pura (DataFrames entram, resultado sai), não lê arquivo e
recebe a competência por parâmetro. O elemento implementado é declarado em
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
    competencia: str,
) -> dict[str, pd.DataFrame]:
    """Devolve a apuração simulada e a contribuição por elemento."""
    vendas = bases["vendas"]
    vendas_periodo = vendas[vendas["competencia"] == competencia]
    total_por_matricula = vendas_periodo.groupby("matricula")["vlr_venda"].sum()

    simulada = apuracao_base.copy()
    vendas_alinhadas = simulada["matricula"].map(total_por_matricula).fillna(0.0)
    no_alvo = (simulada["cod_marca"] == _MARCA_ALVO) & (simulada["cod_cargo"] == _CARGO_ALVO)

    nova_comissao = simulada["comissao"].where(~no_alvo, vendas_alinhadas * _PERCENTUAL)
    delta = nova_comissao - simulada["comissao"]
    simulada["comissao"] = nova_comissao

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
