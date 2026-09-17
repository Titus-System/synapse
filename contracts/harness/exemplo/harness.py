"""Harness de referência do contrato (T-034).

Prepara a entrada, chama a função gerada e monta a saída. Versão mínima para os
testes; a implementação real é do worker (T-033, T-064, T-066).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

type RegraFn = Callable[
    [dict[str, pd.DataFrame], pd.DataFrame, list[str]],
    dict[str, pd.DataFrame],
]


def preparar(bases: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Devolve cópias das bases, para o código gerado não alterar as originais."""
    return {nome: tabela.copy(deep=True) for nome, tabela in bases.items()}


def chamar(
    regra: RegraFn,
    bases: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencias: list[str],
) -> dict[str, pd.DataFrame]:
    """Chama a função gerada com cópias das entradas."""
    return regra(preparar(bases), apuracao_base.copy(deep=True), competencias)


def _quebra_por_dimensao(delta_por_dim: "pd.Series[float]") -> dict[str, float]:
    return {str(chave): float(valor) for chave, valor in delta_por_dim.items()}


def montar_resultado(
    saida: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencias: list[str],
    orcamento: float,
) -> dict[str, Any]:
    """Agrega a saída da função gerada no resultado-simulacao.

    O orçamento entra aqui só para o exemplo ficar completo; em produção quem o
    aplica é o worker, fora do container (T-066).
    """
    simulada = saida["apuracao_simulada"]
    contribuicoes = saida["contribuicoes"]

    baseline = float(apuracao_base["comissao"].sum())
    simulado = float(simulada["comissao"].sum())
    diferenca_abs = simulado - baseline
    diferenca_pct = diferenca_abs / baseline if baseline else 0.0

    # matricula sozinha não é chave única quando o período tem mais de uma
    # competência: a mesma matrícula aparece uma vez por mês processado.
    chave = ["matricula", "competencia"]
    base_indexada = apuracao_base.set_index(chave)
    simulada_indexada = simulada.set_index(chave)
    delta = simulada_indexada["comissao"] - base_indexada["comissao"]
    dims = base_indexada[["cod_loja", "cod_marca", "cod_cargo"]].assign(delta=delta)
    dims = dims.reset_index()

    decomposicao = {
        "elemento": {
            str(ref): float(valor)
            for ref, valor in contribuicoes.groupby("elemento_ref")["delta"].sum().items()
        },
        "loja": _quebra_por_dimensao(dims.groupby("cod_loja")["delta"].sum()),
        "marca": _quebra_por_dimensao(dims.groupby("cod_marca")["delta"].sum()),
        "cargo": _quebra_por_dimensao(dims.groupby("cod_cargo")["delta"].sum()),
        # toda competência do período entra, mesmo com delta zero - uma regra
        # sazonal processada junto com meses fora da sua vigência não afeta
        # aqueles meses, mas eles foram simulados e precisam aparecer.
        "competencia": {
            competencia: float(dims.loc[dims["competencia"] == competencia, "delta"].sum())
            for competencia in competencias
        },
    }

    return {
        "totais": {
            "baseline": baseline,
            "simulado": simulado,
            "diferenca_abs": diferenca_abs,
            "diferenca_pct": diferenca_pct,
            "orcamento": float(orcamento),
        },
        "assercoes": [
            {"nome": "sem_comissao_negativa", "resultado": "ok", "detalhe": None},
        ],
        "decomposicao": decomposicao,
    }
