"""Extraction and validation of the rule code the model returns.

The code is untrusted data: it is only parsed with `ast.parse`, never compiled, imported or
executed here (AGENTS.md Security). Running it is exclusively the worker's job.
"""

import ast
import re

LINGUAGEM = "python"

_BLOCO_PYTHON = re.compile(r"```python[ \t]*\n(.*?)```", re.DOTALL)
_PARAMETROS_REGRA = ["bases", "apuracao_base", "competencias"]


class CodigoInvalidoError(Exception):
    """The model's reply does not carry exactly one valid `regra.py`.

    Never carries the reply or the code - only which check failed.
    """


def extrair_codigo(resposta: str) -> str:
    """Return the `regra.py` source from the reply's single ```python block.

    Raises `CodigoInvalidoError` when there is no block or more than one, when the source is
    not valid Python, or when it does not define `aplicar_regra(bases, apuracao_base,
    competencias)` at module level (`app/prompts/regrafn.md`).
    """
    blocos = _BLOCO_PYTHON.findall(resposta)
    if len(blocos) != 1:
        raise CodigoInvalidoError(f"Expected exactly one python block, found {len(blocos)}")

    fonte: str = blocos[0]
    try:
        modulo = ast.parse(fonte)
    except SyntaxError:
        raise CodigoInvalidoError("Generated code is not valid Python") from None

    if not _define_aplicar_regra(modulo):
        raise CodigoInvalidoError(
            "Generated code does not define aplicar_regra(bases, apuracao_base, competencias)"
        )
    return fonte


def _define_aplicar_regra(modulo: ast.Module) -> bool:
    for no in modulo.body:
        if isinstance(no, ast.FunctionDef) and no.name == "aplicar_regra":
            argumentos = no.args
            nomes = [arg.arg for arg in [*argumentos.posonlyargs, *argumentos.args]]
            return (
                nomes == _PARAMETROS_REGRA
                and argumentos.vararg is None
                and argumentos.kwarg is None
                and not argumentos.kwonlyargs
            )
    return False
