"""Cenário da T-259: três elementos aplicados a todas as matrículas do período."""

import json
from pathlib import Path

from app.sandbox.envelope import VERSAO, Envelope
from app.sandbox.resultado import montar_resultado
from tests.app.execucao.envelopes import CODIGO_ID, JOB_ID
from tests.app.sandbox.test_resultado import assercoes_ok

COMPETENCIAS = ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
ELEMENTOS = ["elem.1", "elem.2", "elem.3"]
# Somente os testes marcados docker executam esta fonte.
REGRA_TRES_ELEMENTOS = """
import pandas as pd

def aplicar_regra(bases, apuracao_base, competencias):
    simulada = apuracao_base.copy()
    simulada["comissao"] += 3.0
    parcelas = []
    for elemento in ["elem.1", "elem.2", "elem.3"]:
        contribuicao = apuracao_base.copy()
        contribuicao["elemento_ref"] = elemento
        contribuicao["delta"] = 1.0
        parcelas.append(contribuicao)
    return {
        "apuracao_simulada": simulada,
        "contribuicoes": pd.concat(parcelas, ignore_index=True),
        "elementos_implementados": ["elem.1", "elem.2", "elem.3"],
    }
"""


def baseline_do_periodo():
    raiz = Path(__file__).resolve().parents[3] / "sandbox/data/domrock/baselines"
    return [
        json.loads(linha)
        for c in COMPETENCIAS
        for linha in (raiz / f"baseline-{c}.jsonl").read_text().splitlines()
    ]


def envelope_do_periodo() -> Envelope:
    # Monta as tabelas conhecidas diretamente: não executa código gerado no host.
    base = baseline_do_periodo()
    montado = montar_resultado(
        {
            "apuracao_simulada": [
                {**registro, "comissao": registro["comissao"] + 3.0} for registro in base
            ],
            "contribuicoes": [
                {**registro, "elemento_ref": e, "delta": 1.0}
                for registro in base
                for e in ELEMENTOS
            ],
        },
        base,
        COMPETENCIAS,
        assercoes=assercoes_ok(),
    )
    return Envelope(
        versao=VERSAO,
        job_id=str(JOB_ID),
        codigo_gerado_id=str(CODIGO_ID),
        competencias=COMPETENCIAS,
        status="sucesso",
        assercoes=assercoes_ok(),
        resultado=montado.resultado,
        linhas=montado.linhas,
        elementos_implementados=ELEMENTOS,
        erro=None,
    )
