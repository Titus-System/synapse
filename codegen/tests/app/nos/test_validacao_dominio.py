import ast
from collections.abc import Mapping
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.nos import validacao_dominio
from app.nos.validacao_dominio import verificar


def _representacao(
    nucleo: Mapping[str, object] | None = None,
    especificacoes: list[object] | None = None,
) -> dict[str, object]:
    nucleo_final: dict[str, object] = {"percentual": Decimal("0.03")}
    if nucleo is not None:
        nucleo_final.update(nucleo)
    return {
        "nucleo": nucleo_final,
        "especificacoes": especificacoes if especificacoes is not None else [],
    }


def _faixa(inferior: object, superior: object) -> dict[str, object]:
    return {
        "ref": "elem.1",
        "construto": "faixa_valor",
        "limite_inferior": inferior,
        "limite_superior": superior,
        "efeito": {"tipo": "bonus_fixo", "valor": Decimal("3500")},
    }


def _janela(inicial: object, final: object) -> dict[str, object]:
    return {
        "ref": "elem.2",
        "construto": "janela_datas",
        "data_inicial": inicial,
        "data_final": final,
        "efeito": {"tipo": "acrescimo_pct", "valor": Decimal("0.01")},
    }


def test_faixa_com_limite_inferior_maior_que_o_superior_e_bloqueada() -> None:
    resultado = verificar(
        _representacao(especificacoes=[_faixa(Decimal("50000"), Decimal("40000"))])
    )

    assert not resultado.liberado
    assert [conflito.elementos for conflito in resultado.conflitos] == [("elem.1",)]


def test_faixa_com_limites_em_ordem_e_liberada() -> None:
    resultado = verificar(
        _representacao(especificacoes=[_faixa(Decimal("40000"), Decimal("50000"))])
    )

    assert resultado.liberado


@pytest.mark.parametrize(
    ("inicial", "final"),
    [("2025-11-24", "2025-11-20"), (date(2025, 11, 24), date(2025, 11, 20))],
)
def test_janela_de_datas_que_termina_antes_de_comecar_e_bloqueada(
    inicial: object, final: object
) -> None:
    resultado = verificar(_representacao(especificacoes=[_janela(inicial, final)]))

    assert [conflito.elementos for conflito in resultado.conflitos] == [("elem.2",)]


def test_janela_de_datas_em_ordem_e_liberada() -> None:
    resultado = verificar(_representacao(especificacoes=[_janela("2025-11-24", "2025-11-30")]))

    assert resultado.liberado


def test_vigencia_com_fim_anterior_ao_inicio_e_bloqueada() -> None:
    resultado = verificar(
        _representacao(nucleo={"vigencia": {"inicio": "2025-11", "fim": "2025-08"}})
    )

    assert [conflito.elementos for conflito in resultado.conflitos] == [("nucleo.vigencia",)]


@pytest.mark.parametrize(
    "vigencia", [{"inicio": "2025-08", "fim": "2025-11"}, {"inicio": "2025-11", "fim": "2025-11"}]
)
def test_vigencia_com_inicio_ate_o_fim_e_liberada(vigencia: dict[str, str]) -> None:
    resultado = verificar(_representacao(nucleo={"vigencia": vigencia}))

    assert resultado.liberado


def test_condicao_por_limiar_sem_escopo_de_agregacao_e_bloqueada() -> None:
    limiar = {
        "ref": "elem.3",
        "construto": "condicao_limiar",
        "metrica": "venda_total",
        "operador": ">=",
        "limiar": Decimal("50000"),
    }

    resultado = verificar(_representacao(especificacoes=[limiar]))

    assert [conflito.elementos for conflito in resultado.conflitos] == [("elem.3",)]


def test_condicao_por_limiar_com_escopo_de_agregacao_e_liberada() -> None:
    limiar = {
        "ref": "elem.3",
        "construto": "condicao_limiar",
        "metrica": "venda_total",
        "escopo_agregacao": "loja",
        "operador": ">=",
        "limiar": Decimal("50000"),
    }

    resultado = verificar(_representacao(especificacoes=[limiar]))

    assert resultado.liberado


def test_representacao_coerente_com_varios_elementos_e_liberada() -> None:
    limiar = {
        "ref": "elem.3",
        "construto": "condicao_limiar",
        "metrica": "venda_total",
        "escopo_agregacao": "loja",
        "operador": ">=",
        "limiar": Decimal("50000"),
    }
    regra = _representacao(
        nucleo={"vigencia": {"inicio": "2025-08", "fim": "2025-11"}, "percentual": Decimal("0.03")},
        especificacoes=[
            _faixa(Decimal("40000"), Decimal("50000")),
            _janela("2025-11-24", "2025-11-30"),
            limiar,
        ],
    )

    assert verificar(regra).liberado


def test_nucleo_sem_percentual_e_bloqueado_nomeando_o_campo() -> None:
    regra: dict[str, object] = {"nucleo": {"loja": ["13"]}, "especificacoes": []}

    resultado = verificar(regra)

    assert [conflito.elementos for conflito in resultado.conflitos] == [("nucleo.percentual",)]


def test_nucleo_so_com_percentual_e_liberado() -> None:
    regra: dict[str, object] = {"nucleo": {"percentual": Decimal("0.03")}, "especificacoes": []}

    assert verificar(regra).liberado


def test_percentual_negativo_e_bloqueado() -> None:
    regra: dict[str, object] = {"nucleo": {"percentual": Decimal("-0.01")}, "especificacoes": []}

    resultado = verificar(regra)

    assert [conflito.elementos for conflito in resultado.conflitos] == [("nucleo.percentual",)]


def test_percentual_zero_nao_e_negativo_e_liberado() -> None:
    regra: dict[str, object] = {"nucleo": {"percentual": Decimal("0")}, "especificacoes": []}

    assert verificar(regra).liberado


def test_valor_incluido_no_nucleo_e_excluido_e_bloqueado() -> None:
    regra: dict[str, object] = {
        "nucleo": {"percentual": Decimal("0.03"), "cargo": ["100", "150"]},
        "especificacoes": [
            {"ref": "elem.1", "construto": "exclusao", "dimensao": "cargo", "valores": ["150"]}
        ],
    }

    resultado = verificar(regra)

    assert [conflito.elementos for conflito in resultado.conflitos] == [("nucleo.cargo", "elem.1")]


def test_exclusao_de_valor_fora_do_nucleo_nao_bloqueia() -> None:
    regra: dict[str, object] = {
        "nucleo": {"percentual": Decimal("0.03"), "cargo": ["100"]},
        "especificacoes": [
            {"ref": "elem.1", "construto": "exclusao", "dimensao": "cargo", "valores": ["150"]}
        ],
    }

    assert verificar(regra).liberado


def test_exclusao_quando_nucleo_nao_lista_a_dimensao_nao_bloqueia() -> None:
    regra: dict[str, object] = {
        "nucleo": {"percentual": Decimal("0.03")},
        "especificacoes": [
            {"ref": "elem.1", "construto": "exclusao", "dimensao": "cargo", "valores": ["150"]}
        ],
    }

    assert verificar(regra).liberado


def test_verificar_e_deterministica_e_nao_muta_a_representacao() -> None:
    regra = _representacao(especificacoes=[_faixa(Decimal("50000"), Decimal("40000"))])
    copia = deepcopy(regra)

    assert verificar(regra) == verificar(regra)
    assert regra == copia


def test_verificacao_de_dominio_nao_importa_llm_nem_acesso_a_base() -> None:
    fonte = Path(validacao_dominio.__file__).read_text(encoding="utf-8")
    importados: set[str] = set()
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.Import):
            importados.update(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module is not None:
            importados.add(no.module)

    proibidos = (
        "app.mensageria",
        "app.config",
        "httpx",
        "aio_pika",
        "psycopg",
        "sqlalchemy",
        "openai",
        "anthropic",
        "langchain",
        "langgraph",
    )
    ofensores = {
        modulo
        for modulo in importados
        for prefixo in proibidos
        if modulo == prefixo or modulo.startswith(f"{prefixo}.")
    }

    assert ofensores == set()
