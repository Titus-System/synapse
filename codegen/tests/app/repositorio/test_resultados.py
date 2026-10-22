from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
import simplejson

from app.repositorio.resultados import (
    ResultadoIndisponivelError,
    buscar_taxas_simuladas,
    buscar_totais,
)
from app.sugestao_adaptacao import TaxaSimulada

JOB_ID = uuid4()
RESULTADO_ID = uuid4()
REGRA_ID = uuid4()


class _ResultadoFalso:
    def __init__(self, linha: Any) -> None:
        self._linha = linha

    def mappings(self) -> "_ResultadoFalso":
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        linha: dict[str, Any] | None = self._linha
        return linha

    def all(self) -> list[dict[str, Any]]:
        linhas: list[dict[str, Any]] = self._linha
        return linhas


class _SessaoFalsa:
    def __init__(self, linha: Any) -> None:
        self._linha = linha
        self.executado_com: tuple[Any, Any] | None = None

    async def execute(self, statement: Any, params: Any) -> _ResultadoFalso:
        self.executado_com = (statement, params)
        return _ResultadoFalso(self._linha)


def _sessionmaker(linha: Any) -> Any:
    sessao = _SessaoFalsa(linha)

    @asynccontextmanager
    async def sessoes() -> AsyncIterator[_SessaoFalsa]:
        yield sessao

    sessoes.sessao = sessao  # type: ignore[attr-defined]
    return sessoes


async def test_buscar_totais_le_os_totais_que_a_adaptacao_precisa() -> None:
    linha = {
        "totais": {
            "baseline": Decimal("480312.00"),
            "simulado": Decimal("492100.00"),
            "orcamento": Decimal("485000.00"),
        }
    }

    totais = await buscar_totais(_sessionmaker(linha), JOB_ID, RESULTADO_ID)

    assert totais.baseline == Decimal("480312.00")
    assert totais.simulado == Decimal("492100.00")
    assert totais.orcamento == Decimal("485000.00")


async def test_buscar_totais_decodifica_jsonb_recebido_como_texto_preservando_decimal() -> None:
    """Sem o `::text` o driver devolveria float, e o total viraria um número aproximado."""
    bruto = simplejson.dumps(
        {
            "baseline": Decimal("480312.01234567890123456789"),
            "simulado": Decimal("492100.01"),
            "orcamento": Decimal("485000.00"),
        }
    )

    totais = await buscar_totais(_sessionmaker({"totais": bruto}), JOB_ID, RESULTADO_ID)

    assert totais.baseline == Decimal("480312.01234567890123456789")
    assert totais.simulado == Decimal("492100.01")
    assert isinstance(totais.simulado, Decimal)


async def test_buscar_totais_filtra_pelo_job_do_resultado() -> None:
    """Resultado de outro job não pode embasar a adaptação deste."""
    sessoes = _sessionmaker({"totais": {"baseline": 0, "simulado": 1, "orcamento": 2}})

    await buscar_totais(sessoes, JOB_ID, RESULTADO_ID)

    _, parametros = sessoes.sessao.executado_com
    assert parametros == {"resultado_id": str(RESULTADO_ID), "job_id": str(JOB_ID)}


async def test_buscar_totais_recusa_resultado_inexistente() -> None:
    with pytest.raises(ResultadoIndisponivelError):
        await buscar_totais(_sessionmaker(None), JOB_ID, RESULTADO_ID)


@pytest.mark.parametrize(
    "totais",
    [{}, {"simulado": Decimal("1")}, {"orcamento": Decimal("1")}, {"simulado": 2, "orcamento": 1}],
    ids=["vazio", "sem_orcamento", "sem_simulado", "sem_baseline"],
)
async def test_buscar_totais_recusa_desfecho_sem_os_tres_totais(totais: dict[str, Any]) -> None:
    """Fora de `sucesso` o worker não grava totais, e não há razão a aplicar."""
    with pytest.raises(ResultadoIndisponivelError):
        await buscar_totais(_sessionmaker({"totais": totais}), JOB_ID, RESULTADO_ID)


async def test_buscar_taxas_simuladas_le_taxa_e_comissao_em_decimal_exato() -> None:
    linhas = [
        {
            "nucleo": simplejson.dumps({"percentual": Decimal("0.0183"), "loja": ["13"]}),
            "especificacoes": "[]",
            "totais": simplejson.dumps({"simulado": Decimal("492100.012345678901234567")}),
        },
        {
            "nucleo": simplejson.dumps({"percentual": Decimal("0.025")}),
            "especificacoes": "[]",
            "totais": simplejson.dumps({"simulado": Decimal("500000")}),
        },
    ]

    taxas = await buscar_taxas_simuladas(_sessionmaker(linhas), JOB_ID, REGRA_ID)

    assert taxas == [
        TaxaSimulada(Decimal("0.0183"), Decimal("492100.012345678901234567")),
        TaxaSimulada(Decimal("0.025"), Decimal("500000")),
    ]


async def test_buscar_taxas_simuladas_le_a_primeira_taxa_positiva_de_qualquer_estrutura() -> None:
    """Sem percentual uniforme, a referência é a primeira taxa positiva, por cargo ou por efeito."""
    linhas = [
        {
            "nucleo": simplejson.dumps(
                {
                    "taxas_por_cargo": [
                        {"cargo": "200", "percentual": Decimal("0")},
                        {"cargo": "100", "percentual": Decimal("0.0243")},
                    ]
                }
            ),
            "especificacoes": simplejson.dumps(
                [{"ref": "elem.1", "construto": "bonus_fixo", "valor": Decimal("350")}]
            ),
            "totais": simplejson.dumps({"simulado": Decimal("2600")}),
        },
        {
            "nucleo": simplejson.dumps({"percentual": Decimal("0")}),
            "especificacoes": simplejson.dumps(
                [
                    {
                        "ref": "elem.1",
                        "construto": "janela_datas",
                        "efeito": {"tipo": "substituicao_pct", "valor": Decimal("0.04")},
                    }
                ]
            ),
            "totais": simplejson.dumps({"simulado": Decimal("3000")}),
        },
    ]

    taxas = await buscar_taxas_simuladas(_sessionmaker(linhas), JOB_ID, REGRA_ID)

    assert taxas == [
        TaxaSimulada(Decimal("0.0243"), Decimal("2600")),
        TaxaSimulada(Decimal("0.04"), Decimal("3000")),
    ]


async def test_buscar_taxas_simuladas_parte_da_regra_simulada_no_job() -> None:
    sessoes = _sessionmaker([])

    await buscar_taxas_simuladas(sessoes, JOB_ID, REGRA_ID)

    _, parametros = sessoes.sessao.executado_com
    assert parametros == {"regra_id": str(REGRA_ID), "job_id": str(JOB_ID), "limite": 3}


@pytest.mark.parametrize(
    "linha",
    [
        {"nucleo": "{}", "especificacoes": "[]", "totais": '{"simulado": 1}'},
        {
            "nucleo": '{"taxas_por_cargo": [{"cargo": "100", "percentual": 0}]}',
            "especificacoes": "[]",
            "totais": '{"simulado": 1}',
        },
        {"nucleo": '{"percentual": 0.02}', "especificacoes": "[]", "totais": "{}"},
        {"nucleo": '{"percentual": 0.02}', "especificacoes": "[]", "totais": None},
    ],
    ids=["sem_percentual", "sem_taxa_positiva", "sem_simulado", "sem_totais"],
)
async def test_buscar_taxas_simuladas_recusa_versao_sem_taxa_ou_comissao(
    linha: dict[str, Any],
) -> None:
    with pytest.raises(ResultadoIndisponivelError):
        await buscar_taxas_simuladas(_sessionmaker([linha]), JOB_ID, REGRA_ID)
