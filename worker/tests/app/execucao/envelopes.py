"""Saídas de container montadas à mão, para os testes da classificação e do consumidor.

O que um container real produziria (ou o que ele não produziria: código hostil escreve
qualquer byte no stdout), sem subir nenhum.
"""

import copy
import json
from typing import Any
from uuid import UUID

from app.execucao.container import SaidaBruta
from app.execucao.preparo import PayloadContainer
from app.sandbox.envelope import SAIDA_SUCESSO, VERSAO

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

FALHA = {
    "tipo": "KeyError",
    "mensagem": "'cod_loja'",
    "traceback": '  File "<regra>", line 3, in aplicar_regra\n',
}


def envelope(status: str = "sucesso", **mudancas: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "versao": VERSAO,
        "job_id": str(JOB_ID),
        "codigo_gerado_id": str(CODIGO_ID),
        "competencias": COMPETENCIAS,
        "status": status,
        "assercoes": [ASSERCAO_OK],
        "resultado": copy.deepcopy(RESULTADO),
        "erro": None,
    }
    if status == "assercao_violada":
        base |= {"assercoes": [ASSERCAO_VIOLADA], "resultado": None}
    if status == "erro_codigo":
        base |= {"assercoes": [], "resultado": None, "erro": dict(FALHA)}
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
