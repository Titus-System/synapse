import pytest

from app.codigo_gerado import CodigoInvalidoError, extrair_codigo

_FONTE = "def aplicar_regra(bases, apuracao_base, competencias):\n    return {}\n"


def _resposta(*blocos: str) -> str:
    return "Segue o código.\n" + "\n".join(f"```python\n{b}```" for b in blocos) + "\nFim."


def test_extrai_o_unico_bloco_python_verbatim() -> None:
    assert extrair_codigo(_resposta(_FONTE)) == _FONTE


def test_nunca_executa_o_codigo_extraido() -> None:
    fonte = 'raise RuntimeError("executado")\n' + _FONTE

    assert extrair_codigo(_resposta(fonte)) == fonte


@pytest.mark.parametrize(
    "resposta",
    [
        pytest.param("sem bloco nenhum", id="zero-blocos"),
        pytest.param(f"```\n{_FONTE}```", id="bloco-sem-linguagem"),
        pytest.param(_resposta(_FONTE, _FONTE), id="dois-blocos"),
        pytest.param(_resposta("def aplicar_regra(:\n"), id="sintaxe-invalida"),
        pytest.param(
            _resposta("def outra(bases, apuracao_base, competencias): ...\n"), id="sem-funcao"
        ),
        pytest.param(_resposta("def aplicar_regra(bases, competencias): ...\n"), id="assinatura"),
        pytest.param(
            _resposta("def aplicar_regra(bases, apuracao_base, competencias, *extra): ...\n"),
            id="varargs",
        ),
        pytest.param(
            _resposta("async def aplicar_regra(bases, apuracao_base, competencias): ...\n"),
            id="async",
        ),
        pytest.param(
            _resposta(
                "class Regra:\n" "    def aplicar_regra(bases, apuracao_base, competencias): ...\n"
            ),
            id="fora-do-modulo",
        ),
    ],
)
def test_recusa_resposta_sem_um_regra_py_valido(resposta: str) -> None:
    with pytest.raises(CodigoInvalidoError):
        extrair_codigo(resposta)


def test_erro_nao_carrega_o_codigo() -> None:
    with pytest.raises(CodigoInvalidoError) as erro:
        extrair_codigo(_resposta("segredo = 1\n"))

    assert "segredo" not in str(erro.value)
