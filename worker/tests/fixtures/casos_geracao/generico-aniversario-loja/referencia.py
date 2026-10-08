"""Referência do caso generico-aniversario-loja (T-243): um elemento que os dados não permitem.

Roda apenas no sandbox, como o código gerado. Nenhuma base traz a data de aniversário da loja,
então a regra não pode ser simulada por inteiro: como o contrato do harness manda, a função
levanta NotImplementedError nomeando o elemento, em vez de devolver um número sem ele.
"""

from __future__ import annotations

import pandas as pd


def aplicar_regra(
    bases: dict[str, pd.DataFrame],
    apuracao_base: pd.DataFrame,
    competencias: list[str],
) -> dict[str, pd.DataFrame | list[str]]:
    raise NotImplementedError("elem.1: as bases não têm a data de aniversário da loja")
