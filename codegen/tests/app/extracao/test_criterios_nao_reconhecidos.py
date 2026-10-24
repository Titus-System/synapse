"""Critério não reconhecido pela extração: conflito na validação, e não resíduo na regra.

Um elemento genérico que só repete um critério do núcleo não reconhecido não pode ser
implementado pelo código gerado, e o worker interromperia a simulação na conferência de
cobertura mesmo depois de a correção completar o núcleo. Os casos seguem, reduzidos, os textos
que levaram a essa interrupção.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.extracao.construtos.generico import DESCRICAO_SEM_LASTRO
from app.extracao.correcao import aplicar_operacoes_correcao
from app.extracao.modelos import ResultadoExtracao
from app.extracao.motor import extrair_regra
from app.nos.codigos_conflito import CodigoConflito
from app.nos.validacao_dominio import ResultadoValidacao, verificar
from app.representacao_regra import RepresentacaoRegra
from tests.app.extracao.test_motor import METADADOS, modelo_falso

PUBLICADAS = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
PARAMETROS = {"orcamento": Decimal("200000"), "meta_venda": Decimal("1000000")}
TODOS_OS_CARGOS = {"valor": [], "trecho": "todos os cargos"}
UM_POR_CENTO = {"valor": Decimal("0.01"), "trecho": "1%"}


async def _extrair(
    texto: str,
    nucleo: dict[str, Any],
    *,
    elementos: Sequence[dict[str, str]] = (),
    publicadas: Sequence[str] = PUBLICADAS,
) -> ResultadoExtracao:
    modelo = modelo_falso({"nucleo": nucleo, "elementos": list(elementos), "parametros": {}})
    return await extrair_regra(texto, publicadas, modelo=modelo, metadados_modelo=METADADOS)


def _validar_extraida(resultado: ResultadoExtracao) -> ResultadoValidacao:
    # Os critérios que `nucleo_sem_lastro` leria de `extracoes_regras.rebaixamentos`.
    criterios = frozenset(
        r.ref.removeprefix("nucleo.")
        for r in resultado.rebaixamentos
        if r.ref.startswith("nucleo.")
    )
    return verificar(
        resultado.representacao.para_contrato(),
        PARAMETROS,
        competencias_publicadas=PUBLICADAS,
        nucleo_sem_lastro=criterios,
    )


def _corrigir(
    regra: RepresentacaoRegra, texto: str, *operacoes: dict[str, Any]
) -> tuple[RepresentacaoRegra, list[Any]]:
    corrigida, _, diagnosticos = aplicar_operacoes_correcao(
        regra, {}, {"operacoes": list(operacoes)}, PUBLICADAS, texto_correcao=texto
    )
    return corrigida, list(diagnosticos)


def _validar_corrigida(regra: RepresentacaoRegra) -> ResultadoValidacao:
    # A versão de uma correção não nasceu da extração e não tem critério sem lastro.
    return verificar(regra.para_contrato(), PARAMETROS, competencias_publicadas=PUBLICADAS)


async def test_loja_citada_sem_lastro_pede_correcao_e_a_corrigida_segue_sem_residuo() -> None:
    texto = "loja sessenta e oito marca preto para todos os cargos com 1% de comissão"
    extraida = await _extrair(
        texto,
        {
            # O modelo devolveu o código no lugar da citação, que não está no texto.
            "loja": [{"valor": "68", "trecho": "loja 68"}],
            "marca": [{"valor": "PRETO", "trecho": "marca preto"}],
            "cargo": TODOS_OS_CARGOS,
            "percentual": UM_POR_CENTO,
        },
    )

    assert extraida.representacao.para_contrato()["especificacoes"] == []
    assert [(c.elementos, c.codigo) for c in _validar_extraida(extraida).conflitos] == [
        (("nucleo.loja",), CodigoConflito.NUCLEO_SEM_LASTRO)
    ]

    correcao = "loja 68"
    corrigida, diagnosticos = _corrigir(
        extraida.representacao,
        correcao,
        {
            "tipo": "definir_nucleo",
            "trecho": correcao,
            "campo": "loja",
            "valor": [{"valor": "68", "trecho": correcao}],
        },
    )

    assert diagnosticos == []
    assert corrigida.para_contrato()["especificacoes"] == []
    assert _validar_corrigida(corrigida).liberado


async def test_vigencia_sem_periodo_reconhecido_pede_correcao_em_vez_do_periodo_simulado() -> None:
    texto = "loja 68 para todas as marcas e todos os cargos com 1% e a validade será novembro"
    extraida = await _extrair(
        texto,
        {
            "vigencia": {"valor": {"inicio": "2025-11", "fim": "2025-11"}, "trecho": "novembro"},
            "loja": [{"valor": "68", "trecho": "loja 68"}],
            "marca": {"valor": [], "trecho": "todas as marcas"},
            "cargo": TODOS_OS_CARGOS,
            "percentual": UM_POR_CENTO,
        },
        # Com dois anos publicados, o mês sem ano não se resolve.
        publicadas=["2024-12", "2025-11"],
    )

    assert "vigencia" not in extraida.representacao.para_contrato()["nucleo"]  # type: ignore[operator]
    assert extraida.representacao.para_contrato()["especificacoes"] == []
    assert [(c.elementos, c.codigo) for c in _validar_extraida(extraida).conflitos] == [
        (("nucleo.vigencia",), CodigoConflito.NUCLEO_SEM_LASTRO)
    ]

    correcao = "a validade é novembro de 2025"
    corrigida, diagnosticos = _corrigir(
        extraida.representacao,
        correcao,
        {
            "tipo": "definir_nucleo",
            "trecho": correcao,
            "campo": "vigencia",
            "valor": {
                "valor": {"inicio": "2025-11", "fim": "2025-11"},
                "trecho": "novembro de 2025",
            },
        },
    )

    assert diagnosticos == []
    assert corrigida.para_contrato()["especificacoes"] == []
    assert _validar_corrigida(corrigida).liberado


async def test_taxas_por_cargo_sem_lastro_pedem_correcao_e_a_corrigida_segue_sem_residuo() -> None:
    texto = "loja 68 marca preto, percentual de 1%, 2% para vendedor de loja e gerente"
    extraida = await _extrair(
        texto,
        {
            "loja": [{"valor": "68", "trecho": "loja 68"}],
            "marca": [{"valor": "PRETO", "trecho": "marca preto"}],
            # Um trecho com as duas taxas não associa cada uma ao seu cargo.
            "taxas_por_cargo": [
                {"valor": {"cargo": "100", "percentual": Decimal("0.01")}, "trecho": "1%, 2%"},
                {"valor": {"cargo": "150", "percentual": Decimal("0.02")}, "trecho": "1%, 2%"},
            ],
        },
    )

    assert extraida.representacao.para_contrato()["especificacoes"] == []
    assert [(c.elementos, c.codigo) for c in _validar_extraida(extraida).conflitos] == [
        (("nucleo.taxas_por_cargo",), CodigoConflito.NUCLEO_SEM_LASTRO),
        (("nucleo.cargo",), CodigoConflito.ESCOPO_AUSENTE),
    ]

    correcao = "1% pro vendedor de loja e 2% pro gerente"
    corrigida, diagnosticos = _corrigir(
        extraida.representacao,
        correcao,
        {
            "tipo": "definir_taxa_cargo",
            "trecho": "1% pro vendedor de loja",
            "valor": {
                "valor": {"cargo": "100", "percentual": Decimal("0.01")},
                "trecho": "1% pro vendedor de loja",
            },
        },
        {
            "tipo": "definir_taxa_cargo",
            "trecho": "2% pro gerente",
            "valor": {
                "valor": {"cargo": "150", "percentual": Decimal("0.02")},
                "trecho": "2% pro gerente",
            },
        },
    )

    assert diagnosticos == []
    assert corrigida.para_contrato()["especificacoes"] == []
    assert _validar_corrigida(corrigida).liberado


async def test_elemento_sem_trecho_no_texto_pede_correcao_e_a_substituicao_libera() -> None:
    texto = "loja 68 para todas as marcas e todos os cargos com 1% de comissão"
    extraida = await _extrair(
        texto,
        {
            "loja": [{"valor": "68", "trecho": "loja 68"}],
            "marca": {"valor": [], "trecho": "todas as marcas"},
            "cargo": TODOS_OS_CARGOS,
            "percentual": UM_POR_CENTO,
        },
        elementos=[
            {
                "construto_pretendido": "generico",
                "descricao": "bônus de R$ 350 para vendedores",
                "trecho": "bônus de R$ 350 para vendedores",
            }
        ],
    )
    especificacoes = extraida.representacao.para_contrato()["especificacoes"]

    assert especificacoes == [
        {"ref": "elem.1", "construto": "generico", "descricao": DESCRICAO_SEM_LASTRO}
    ]
    assert [(c.elementos, c.codigo) for c in _validar_extraida(extraida).conflitos] == [
        (("elem.1",), CodigoConflito.ELEMENTO_SEM_LASTRO)
    ]

    correcao = "bônus de R$ 350 para vendedores"
    corrigida, diagnosticos = _corrigir(
        extraida.representacao,
        correcao,
        {
            "tipo": "substituir_elemento",
            "ref": "elem.1",
            "trecho": correcao,
            "elemento": {
                "construto_pretendido": "generico",
                "descricao": correcao,
                "trecho": correcao,
            },
        },
    )

    assert corrigida.para_contrato()["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": correcao}
    ]
    assert [d.ref for d in diagnosticos] == ["elem.1"]
    assert _validar_corrigida(corrigida).liberado
