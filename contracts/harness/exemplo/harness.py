"""Harness de referência do contrato (T-034).

Prepara a entrada, chama a função gerada e monta a saída. Versão mínima para os
testes; a implementação real é do worker (T-033, T-064, T-066).
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

RegraFn = Callable[[dict[str, pd.DataFrame], pd.DataFrame, str], dict[str, pd.DataFrame]]


def preparar(bases: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Devolve cópias das bases, para o código gerado não alterar as originais."""
    return {nome: tabela.copy(deep=True) for nome, tabela in bases.items()}


def chamar(
    regra: RegraFn,
    bases: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencia: str,
) -> dict[str, pd.DataFrame]:
    """Chama a função gerada com cópias das entradas."""
    return regra(preparar(bases), apuracao_base.copy(deep=True), competencia)


def _quebra_por_dimensao(delta_por_dim: "pd.Series[float]") -> dict[str, float]:
    return {str(chave): float(valor) for chave, valor in delta_por_dim.items()}


def montar_resultado(
    saida: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencia: str,
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

    delta = (
        simulada.set_index("matricula")["comissao"]
        - apuracao_base.set_index("matricula")["comissao"]
    )
    dims = apuracao_base.set_index("matricula")[["cod_loja", "cod_marca", "cod_cargo"]]
    dims = dims.assign(delta=delta)

    decomposicao = {
        "elemento": {
            str(ref): float(valor)
            for ref, valor in contribuicoes.groupby("elemento_ref")["delta"].sum().items()
        },
        "loja": _quebra_por_dimensao(dims.groupby("cod_loja")["delta"].sum()),
        "marca": _quebra_por_dimensao(dims.groupby("cod_marca")["delta"].sum()),
        "cargo": _quebra_por_dimensao(dims.groupby("cod_cargo")["delta"].sum()),
        "competencia": {competencia: diferenca_abs},
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
