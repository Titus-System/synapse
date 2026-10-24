import ast
from collections.abc import Mapping
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.extracao.construtos.generico import DESCRICAO_SEM_LASTRO
from app.nos import validacao_dominio
from app.nos.codigos_conflito import CodigoConflito
from app.nos.validacao_dominio import verificar


def _representacao(
    nucleo: Mapping[str, object] | None = None,
    especificacoes: list[object] | None = None,
) -> dict[str, object]:
    nucleo_final: dict[str, object] = {
        "loja": [],
        "marca": [],
        "cargo": [],
        "percentual": Decimal("0.03"),
    }
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


def _limiar_sem_escopo() -> dict[str, object]:
    return {
        "ref": "elem.3",
        "construto": "condicao_limiar",
        "metrica": "venda_total",
        "operador": ">=",
        "limiar": Decimal("50000"),
    }


def _generico_sem_lastro(ref: str) -> dict[str, object]:
    return {"ref": ref, "construto": "generico", "descricao": DESCRICAO_SEM_LASTRO}


_REGRAS_COM_UM_CONFLITO: list[tuple[CodigoConflito, dict[str, object]]] = [
    (
        CodigoConflito.TAXA_CARGO_CONTRADITORIA,
        {
            "nucleo": {
                "cargo": ["100"],
                "taxas_por_cargo": [
                    {"cargo": "100", "percentual": Decimal("0.03")},
                    {"cargo": "100", "percentual": Decimal("0.05")},
                ],
            },
            "especificacoes": [],
        },
    ),
    (
        CodigoConflito.TAXA_CARGO_FORA_ESCOPO,
        {
            "nucleo": {
                "cargo": ["100"],
                "taxas_por_cargo": [
                    {"cargo": "150", "percentual": Decimal("0.03")},
                ],
            },
            "especificacoes": [],
        },
    ),
    (
        CodigoConflito.TAXA_CARGO_DESCONHECIDO,
        {
            "nucleo": {
                "cargo": ["999"],
                "taxas_por_cargo": [
                    {"cargo": "999", "percentual": Decimal("0.03")},
                ],
            },
            "especificacoes": [],
        },
    ),
    (CodigoConflito.PERCENTUAL_AUSENTE, {"nucleo": {}, "especificacoes": []}),
    (
        CodigoConflito.PERCENTUAL_NEGATIVO,
        {"nucleo": {"percentual": Decimal("-0.01")}, "especificacoes": []},
    ),
    (
        CodigoConflito.VIGENCIA_INVERTIDA,
        _representacao(nucleo={"vigencia": {"inicio": "2025-11", "fim": "2025-08"}}),
    ),
    (
        CodigoConflito.EXCLUSAO_REPETIDA,
        {
            "nucleo": {"percentual": Decimal("0.03"), "cargo": ["100", "150"]},
            "especificacoes": [
                {"ref": "elem.1", "construto": "exclusao", "dimensao": "cargo", "valores": ["150"]}
            ],
        },
    ),
    (
        CodigoConflito.FAIXA_INVERTIDA,
        _representacao(especificacoes=[_faixa(Decimal("50000"), Decimal("40000"))]),
    ),
    (
        CodigoConflito.JANELA_INVERTIDA,
        _representacao(especificacoes=[_janela("2025-11-24", "2025-11-20")]),
    ),
    (
        CodigoConflito.LIMIAR_SEM_ESCOPO,
        _representacao(especificacoes=[_limiar_sem_escopo()]),
    ),
    (
        CodigoConflito.ELEMENTO_SEM_LASTRO,
        _representacao(especificacoes=[_generico_sem_lastro("elem.1")]),
    ),
]


def test_conjunto_fechado_de_codigos_e_o_das_verificacoes_existentes() -> None:
    assert {codigo.value for codigo in CodigoConflito} == {
        "percentual_ausente",
        "percentual_negativo",
        "taxa_cargo_contraditoria",
        "taxa_cargo_fora_escopo",
        "taxa_cargo_desconhecido",
        "escopo_ausente",
        "orcamento_ausente",
        "meta_venda_ausente",
        "vigencia_invertida",
        "exclusao_repetida",
        "faixa_invertida",
        "janela_invertida",
        "limiar_sem_escopo",
        "orcamento_negativo",
        "meta_venda_nao_positiva",
        "competencia_nao_publicada",
        "parametro_sem_lastro",
        "nucleo_sem_lastro",
        "elemento_sem_lastro",
    }


@pytest.mark.parametrize(
    ("codigo", "regra"), _REGRAS_COM_UM_CONFLITO, ids=[c.value for c, _ in _REGRAS_COM_UM_CONFLITO]
)
def test_cada_verificacao_classifica_o_conflito_com_o_seu_codigo(
    codigo: CodigoConflito, regra: dict[str, object]
) -> None:
    resultado = verificar(regra)

    assert [conflito.codigo for conflito in resultado.conflitos] == [codigo]


PUBLICADAS = ("2025-08", "2025-09", "2025-10", "2025-11", "2025-12")
_PARAMETROS_COM_UM_CONFLITO: list[tuple[CodigoConflito, dict[str, object], frozenset[str]]] = [
    (CodigoConflito.ORCAMENTO_AUSENTE, {"orcamento": None}, frozenset()),
    (CodigoConflito.META_VENDA_AUSENTE, {"meta_venda": None}, frozenset()),
    (CodigoConflito.ORCAMENTO_NEGATIVO, {"orcamento": Decimal("-1")}, frozenset()),
    (CodigoConflito.META_VENDA_NAO_POSITIVA, {"meta_venda": Decimal("0")}, frozenset()),
    (
        CodigoConflito.COMPETENCIA_NAO_PUBLICADA,
        {"competencias": ["2025-11", "2026-01"]},
        frozenset(),
    ),
    (CodigoConflito.PARAMETRO_SEM_LASTRO, {}, frozenset({"orcamento"})),
]


def _com_parametros(
    parametros: Mapping[str, object], sem_lastro: frozenset[str] = frozenset()
) -> validacao_dominio.ResultadoValidacao:
    return verificar(
        _representacao(),
        {"orcamento": 500000, "meta_venda": 12000000, **parametros},
        competencias_publicadas=PUBLICADAS,
        sem_lastro=sem_lastro,
    )


def test_toda_verificacao_do_modulo_produz_conflito_com_codigo_do_conjunto() -> None:
    cobertos = {codigo for codigo, _ in _REGRAS_COM_UM_CONFLITO}
    cobertos |= {codigo for codigo, _, _ in _PARAMETROS_COM_UM_CONFLITO}
    cobertos.add(CodigoConflito.ESCOPO_AUSENTE)
    cobertos.add(CodigoConflito.NUCLEO_SEM_LASTRO)

    assert cobertos == set(CodigoConflito)
    for _, regra in _REGRAS_COM_UM_CONFLITO:
        for conflito in verificar(regra).conflitos:
            assert isinstance(conflito.codigo, CodigoConflito)


@pytest.mark.parametrize(
    ("codigo", "parametros", "sem_lastro"),
    _PARAMETROS_COM_UM_CONFLITO,
    ids=[c.value for c, _, _ in _PARAMETROS_COM_UM_CONFLITO],
)
def test_cada_verificacao_de_parametro_barra_com_o_seu_codigo(
    codigo: CodigoConflito, parametros: dict[str, object], sem_lastro: frozenset[str]
) -> None:
    resultado = _com_parametros(parametros, sem_lastro)

    assert not resultado.liberado
    assert [conflito.codigo for conflito in resultado.conflitos] == [codigo]


@pytest.mark.parametrize(
    ("parametros", "referencia", "codigo"),
    [
        ({"orcamento": Decimal("-0.01")}, "parametros.orcamento", "orcamento_negativo"),
        ({"meta_venda": Decimal("0")}, "parametros.meta_venda", "meta_venda_nao_positiva"),
        ({"meta_venda": Decimal("-5")}, "parametros.meta_venda", "meta_venda_nao_positiva"),
        (
            {"competencias": ["2025-11", "2026-01"]},
            "parametros.competencias",
            "competencia_nao_publicada",
        ),
    ],
)
def test_parametro_invalido_aponta_o_conflito_na_referencia_do_parametro(
    parametros: dict[str, object], referencia: str, codigo: str
) -> None:
    resultado = _com_parametros(parametros)

    assert [(c.elementos, c.codigo.value) for c in resultado.conflitos] == [((referencia,), codigo)]


@pytest.mark.parametrize(
    "parametros",
    [
        {},
        {"orcamento": Decimal("0")},
        {"competencias": list(PUBLICADAS)},
        {
            "orcamento": Decimal("500000"),
            "meta_venda": Decimal("12000000"),
            "competencias": ["2025-09", "2025-11"],
        },
    ],
    ids=["parametros_preservados", "orcamento_zero", "todas_publicadas", "completos"],
)
def test_parametros_completos_validos_nao_geram_conflito(parametros: dict[str, object]) -> None:
    assert _com_parametros(parametros).liberado


def test_parametros_sem_lastro_saem_na_ordem_do_contrato_com_a_referencia_de_cada_um() -> None:
    resultado = _com_parametros({}, frozenset({"competencias", "meta_venda", "orcamento"}))

    assert [(c.elementos, c.codigo) for c in resultado.conflitos] == [
        (("parametros.orcamento",), CodigoConflito.PARAMETRO_SEM_LASTRO),
        (("parametros.meta_venda",), CodigoConflito.PARAMETRO_SEM_LASTRO),
        (("parametros.competencias",), CodigoConflito.PARAMETRO_SEM_LASTRO),
    ]


def test_motivo_do_parametro_e_texto_do_sistema_sem_o_valor_dito() -> None:
    resultado = _com_parametros(
        {
            "orcamento": Decimal("-123456"),
            "meta_venda": Decimal("-987654"),
            "competencias": ["2031-07"],
        }
    )

    assert len(resultado.conflitos) == 3
    for conflito in resultado.conflitos:
        for dito in ("123456", "987654", "2031", "07"):
            assert dito not in conflito.motivo


def test_conflitos_da_regra_vem_antes_dos_dos_parametros() -> None:
    resultado = verificar(
        _representacao(nucleo={"percentual": Decimal("-0.01")}),
        {"orcamento": Decimal("-1"), "meta_venda": Decimal("12000000")},
        competencias_publicadas=PUBLICADAS,
    )

    assert [c.codigo for c in resultado.conflitos] == [
        CodigoConflito.PERCENTUAL_NEGATIVO,
        CodigoConflito.ORCAMENTO_NEGATIVO,
    ]


def test_regra_com_dois_conflitos_classifica_cada_um_pelo_seu_codigo() -> None:
    regra = _representacao(
        nucleo={"percentual": Decimal("-0.01")},
        especificacoes=[_faixa(Decimal("50000"), Decimal("40000"))],
    )

    resultado = verificar(regra)

    assert [conflito.codigo for conflito in resultado.conflitos] == [
        CodigoConflito.PERCENTUAL_NEGATIVO,
        CodigoConflito.FAIXA_INVERTIDA,
    ]


def test_generico_e_construto_desconhecido_sao_ignorados_sem_falhar() -> None:
    regra = _representacao(
        especificacoes=[
            {"ref": "elem.1", "construto": "generico", "descricao": "x", "campos": {"a": 1}},
            {"ref": "elem.2", "construto": "construto_que_nao_existe", "valor": 1},
        ]
    )

    assert verificar(regra).liberado


def test_generico_sem_trecho_verificavel_e_bloqueado_no_proprio_ref() -> None:
    regra = _representacao(
        especificacoes=[
            {"ref": "elem.1", "construto": "generico", "descricao": "Bônus de R$ 350 por vendedor"},
            _generico_sem_lastro("elem.2"),
        ]
    )

    resultado = verificar(regra)

    assert [(c.elementos, c.codigo) for c in resultado.conflitos] == [
        (("elem.2",), CodigoConflito.ELEMENTO_SEM_LASTRO)
    ]
    assert resultado.conflitos[0].motivo == (
        "condição citada sem trecho reconhecido; descreva a condição novamente"
    )


def test_criterios_do_nucleo_sem_lastro_saem_na_ordem_do_nucleo_com_a_referencia_de_cada_um() -> (
    None
):
    resultado = verificar(
        _representacao(),
        nucleo_sem_lastro=frozenset({"taxas_por_cargo", "cargo", "marca", "loja", "vigencia"}),
    )

    assert [(c.elementos, c.codigo, c.motivo) for c in resultado.conflitos] == [
        (
            ("nucleo.vigencia",),
            CodigoConflito.NUCLEO_SEM_LASTRO,
            "vigência citada sem período reconhecido",
        ),
        (
            ("nucleo.loja",),
            CodigoConflito.NUCLEO_SEM_LASTRO,
            "escopo de loja citado sem código reconhecido; indique os destinatários ou declare "
            "todos",
        ),
        (
            ("nucleo.marca",),
            CodigoConflito.NUCLEO_SEM_LASTRO,
            "escopo de marca citado sem código reconhecido; indique os destinatários ou declare "
            "todos",
        ),
        (
            ("nucleo.cargo",),
            CodigoConflito.NUCLEO_SEM_LASTRO,
            "escopo de cargo citado sem código reconhecido; indique os destinatários ou declare "
            "todos",
        ),
        (
            ("nucleo.taxas_por_cargo",),
            CodigoConflito.NUCLEO_SEM_LASTRO,
            "taxa por cargo citada sem cargo ou percentual reconhecido",
        ),
    ]


def test_escopo_citado_sem_codigo_substitui_o_conflito_de_escopo_nao_informado() -> None:
    regra = {"nucleo": {"marca": [], "cargo": [], "percentual": Decimal("0.03")}}

    resultado = verificar(
        {**regra, "especificacoes": []},
        {"orcamento": Decimal("500000"), "meta_venda": Decimal("12000000")},
        competencias_publicadas=PUBLICADAS,
        nucleo_sem_lastro=frozenset({"loja"}),
    )

    assert [(c.elementos, c.codigo) for c in resultado.conflitos] == [
        (("nucleo.loja",), CodigoConflito.NUCLEO_SEM_LASTRO)
    ]


def test_taxas_citadas_sem_lastro_substituem_o_conflito_de_percentual_ausente() -> None:
    regra = {"nucleo": {"loja": [], "marca": [], "cargo": []}, "especificacoes": []}

    resultado = verificar(regra, nucleo_sem_lastro=frozenset({"taxas_por_cargo"}))

    assert [(c.elementos, c.codigo) for c in resultado.conflitos] == [
        (("nucleo.taxas_por_cargo",), CodigoConflito.NUCLEO_SEM_LASTRO)
    ]


def test_conflito_nao_carrega_o_valor_da_regra_no_codigo() -> None:
    regra = _representacao(especificacoes=[_faixa(Decimal("50000"), Decimal("40000"))])

    (conflito,) = verificar(regra).conflitos

    assert "50000" not in conflito.codigo
