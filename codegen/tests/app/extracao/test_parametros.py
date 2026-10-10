from typing import Any

import pytest

from app.extracao.parametros import validar_parametros

PRIVADO = "CONTEUDO-PRIVADO"


@pytest.mark.parametrize(
    "parametros",
    [
        {"competencias": [PRIVADO]},
        {"orcamento": PRIVADO},
        {"meta_venda": 1, "competencias": ["2025-11", PRIVADO]},
    ],
)
def test_parametros_invalidos_falham_sem_levar_o_valor_na_excecao(
    parametros: dict[str, Any],
) -> None:
    """O validador roda também ao gravar e ao ler a extração, fora da supressão do motor, e a
    exceção do jsonschema traz o valor reprovado, que é o que o texto do usuário disse."""
    with pytest.raises(ValueError) as erro:
        validar_parametros(parametros)

    assert erro.value.__cause__ is None
    assert erro.value.__context__ is None
    assert PRIVADO not in str(erro.value)
    assert PRIVADO not in repr(erro.value)
