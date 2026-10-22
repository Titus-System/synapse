"""Saídas de container montadas à mão, para os testes da classificação e do consumidor.

O que um container real produziria (ou o que ele não produziria: código hostil escreve
qualquer byte no stdout), sem subir nenhum.
"""

import copy
import json
from decimal import ROUND_DOWN, Decimal
from functools import lru_cache
from typing import Any
from uuid import UUID

from app.execucao.baseline import CompetenciaSemBaselineError, LinhasDoBaseline, carregar_baselines
from app.execucao.bases import carregar_bases
from app.execucao.container import SaidaBruta
from app.execucao.preparo import PayloadContainer
from app.sandbox.envelope import SAIDA_SUCESSO, VERSAO
from app.sandbox.regras_base import CENTAVO
from app.sandbox.resultado import ResultadoMontado, montar_resultado

JOB_ID = UUID("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021")
CODIGO_ID = UUID("5d4c3b2a-1f0e-4d9c-8b7a-6e5d4c3b2a19")
COMPETENCIAS = ["2025-08", "2025-11"]
ORCAMENTO = 485000.0

PAYLOAD = PayloadContainer(
    job_id=JOB_ID,
    codigo_gerado_id=CODIGO_ID,
    linguagem="python",
    fonte="def aplicar_regra(bases, apuracao_base, competencias): ...",
    competencias=COMPETENCIAS,
)

ASSERCAO_OK = {"nome": "sem_comissao_negativa", "resultado": "ok", "detalhe": None}
ASSERCAO_VIOLADA = {
    "nome": "sem_comissao_negativa",
    "resultado": "violada",
    "detalhe": "2025-11, matrícula 1234: -12,30",
}

# O que o harness devolve em sucesso: o exemplo do contrato, sem totais.orcamento (T-035).
RESULTADO: dict[str, Any] = {
    "totais": {
        "baseline": 480312.0,
        "simulado": 492100.0,
        "diferenca_abs": 11788.0,
        "diferenca_pct": 0.0245,
    },
    "assercoes": [ASSERCAO_OK],
    "decomposicao": {
        "elemento": {"nucleo.percentual": 8200.0, "elem.1": 3588.0},
        "loja": {"13": 7100.0, "58": 4688.0},
        "marca": {"10": 11788.0},
        "cargo": {"100": 9200.0, "150": 2588.0},
        "competencia": {"2025-08": 0.0, "2025-11": 11788.0},
    },
}

# O que um código que segue o contrato declara para RESULTADO: os elementos da decomposição.
ELEMENTOS_DO_RESULTADO = ["nucleo.percentual", "elem.1"]

FALHA = {
    "tipo": "KeyError",
    "mensagem": "'cod_loja'",
    "traceback": '  File "<regra>", line 3, in aplicar_regra\n',
}


def resultado_para(
    competencias: list[str], a_mais: str = "1000.00", *, meta_venda: float | None = None
) -> dict[str, Any]:
    """O resultado que o harness produziria para estas competências: o baseline é o que o worker
    confere, o congelado ou, com meta, o reapurado sobre as vendas escaladas (T-270), e o
    simulado é ele mais `a_mais`, distribuído por uma regra que altera parte das matrículas."""
    return copy.deepcopy(dict(_montado(tuple(competencias), a_mais, meta_venda).resultado))


def linhas_para(
    competencias: list[str], a_mais: str = "1000.00", *, meta_venda: float | None = None
) -> dict[str, Any]:
    """O detalhamento do mesmo resultado de `resultado_para`, com os mesmos argumentos: os dois
    fecham entre si e com o baseline do worker (T-262)."""
    return copy.deepcopy(dict(_montado(tuple(competencias), a_mais, meta_venda).linhas))


def montar_sobre(
    baseline: LinhasDoBaseline, competencias: list[str], a_mais: Decimal
) -> ResultadoMontado:
    """O que o harness monta (``montar_resultado``, T-035) quando a regra soma `a_mais` à
    comissão de uma em cada três matrículas, em proporção à comissão do baseline e em centavos
    exatos, e atribui cada diferença metade a ``nucleo.percentual`` e metade a ``elem.1``."""
    apuracao_base = [
        {
            "matricula": matricula,
            "competencia": competencia,
            "cod_loja": linha.cod_loja,
            "cod_marca": linha.cod_marca,
            "cod_cargo": linha.cod_cargo,
            "comissao": float(linha.comissao),
        }
        for competencia in competencias
        for matricula, linha in sorted(baseline[competencia].items())
    ]
    alteradas = apuracao_base[::3]
    deltas = _distribuir(a_mais, [Decimal(str(registro["comissao"])) for registro in alteradas])
    delta_por_chave = {
        (str(registro["matricula"]), str(registro["competencia"])): delta
        for registro, delta in zip(alteradas, deltas, strict=True)
    }
    simulada = [
        registro
        | {
            "comissao": float(
                Decimal(str(registro["comissao"]))
                + delta_por_chave.get((str(registro["matricula"]), str(registro["competencia"])), 0)
            )
        }
        for registro in apuracao_base
    ]
    contribuicoes = []
    for (matricula, competencia), delta in delta_por_chave.items():
        metade = (delta / 2).quantize(CENTAVO, rounding=ROUND_DOWN)
        for elemento, parcela in (("nucleo.percentual", metade), ("elem.1", delta - metade)):
            contribuicoes.append(
                {
                    "matricula": matricula,
                    "competencia": competencia,
                    "elemento_ref": elemento,
                    "delta": float(parcela),
                }
            )
    return montar_resultado(
        {"apuracao_simulada": simulada, "contribuicoes": contribuicoes},
        apuracao_base,
        competencias,
        assercoes=[ASSERCAO_OK],  # type: ignore[list-item]
    )


@lru_cache
def _montado(
    competencias: tuple[str, ...], a_mais: str, meta_venda: float | None
) -> ResultadoMontado:
    periodo = list(competencias)
    if meta_venda is None:
        baseline = carregar_baselines().linhas_do_periodo(periodo)
    else:
        baseline = carregar_bases().linhas_na_meta(periodo, meta_venda)
    return montar_sobre(baseline, periodo, Decimal(a_mais))


def _distribuir(total: Decimal, pesos: list[Decimal]) -> list[Decimal]:
    """`total` em parcelas de centavos proporcionais aos pesos, que somam exatamente `total`: a
    sobra do arredondamento fica na parcela de maior peso."""
    soma = sum(pesos, Decimal(0))
    if not soma:
        return [total] + [Decimal(0)] * (len(pesos) - 1)
    parcelas = [(total * peso / soma).quantize(CENTAVO, rounding=ROUND_DOWN) for peso in pesos]
    maior = max(range(len(pesos)), key=lambda indice: pesos[indice])
    parcelas[maior] += total - sum(parcelas, Decimal(0))
    return parcelas


# Uma linha de forma válida, para os testes da forma do envelope com competências que as bases não
# têm: os valores não fecham com baseline nenhum.
LINHA_DE_FORMA: dict[str, Any] = {
    "cod_loja": "13",
    "cod_marca": "10",
    "cod_cargo": "100",
    "comissao_baseline": 100.0,
    "comissao_simulada": 110.0,
    "diferenca": 10.0,
    "contribuicoes": {"elem.1": 10.0},
}


def _linhas_do_envelope(competencias: Any) -> dict[str, Any]:
    """O detalhamento legítimo das competências, ou, com competências fora das bases, uma linha de
    forma válida por competência."""
    try:
        return linhas_para(list(competencias))
    except (CompetenciaSemBaselineError, TypeError):
        return {c: {"MATRIC-1": copy.deepcopy(LINHA_DE_FORMA)} for c in competencias}


def envelope(status: str = "sucesso", **mudancas: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "versao": VERSAO,
        "job_id": str(JOB_ID),
        "codigo_gerado_id": str(CODIGO_ID),
        "competencias": COMPETENCIAS,
        "status": status,
        "assercoes": [ASSERCAO_OK],
        "resultado": copy.deepcopy(RESULTADO),
        "linhas": _linhas_do_envelope(mudancas.get("competencias", COMPETENCIAS)),
        "elementos_implementados": list(ELEMENTOS_DO_RESULTADO),
        "erro": None,
    }
    if status == "assercao_violada":
        base |= {
            "assercoes": [ASSERCAO_VIOLADA],
            "resultado": None,
            "linhas": None,
            "elementos_implementados": None,
        }
    if status == "erro_codigo":
        base |= {
            "assercoes": [],
            "resultado": None,
            "linhas": None,
            "elementos_implementados": None,
            "erro": dict(FALHA),
        }
    return base | mudancas


def saida(
    stdout: bytes | dict[str, Any],
    codigo_saida: int = SAIDA_SUCESSO,
    **mudancas: Any,
) -> SaidaBruta:
    if isinstance(stdout, dict):
        stdout = json.dumps(stdout, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
    campos: dict[str, Any] = {
        "container_id": "c" * 64,
        "codigo_saida": codigo_saida,
        "oom_killed": False,
        "estourou_timeout": False,
        "stdout": stdout,
        "stderr": b"",
        "stdout_truncado": False,
        "stderr_truncado": False,
        "duracao_s": 1.2,
    }
    return SaidaBruta(**(campos | mudancas))
