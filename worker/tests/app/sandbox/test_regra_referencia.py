"""Critérios de aceitação da T-036: a regra de referência sobre a imagem real.

O código, a representação e o resultado esperado ficam em
``contracts/harness/referencia/``; este teste roda o código pela imagem e afere
que a saída bate com o resultado registrado, ancorando no baseline congelado da
T-032. Marcado com ``docker``: ``verify.sh`` só o roda quando o daemon responde.
"""

import json
from pathlib import Path

import pytest

from app.sandbox.envelope import SAIDA_SUCESSO
from tests.app.sandbox.test_executor import bytes_do, payload
from tests.app.sandbox.test_imagem_sandbox import rodar
from tests.app.sandbox.test_resultado import com_orcamento, validar_no_contrato

pytestmark = pytest.mark.docker

REFERENCIA = Path(__file__).resolve().parents[4] / "contracts" / "harness" / "referencia"
FONTE = (REFERENCIA / "regra.py").read_text(encoding="utf-8")
ESPERADO = json.loads((REFERENCIA / "resultado-esperado.json").read_text(encoding="utf-8"))


def test_regra_de_referencia_produz_o_resultado_esperado(imagem: str) -> None:
    processo = rodar(imagem, entrada=bytes_do(payload(FONTE, ("2025-11",))))

    assert processo.returncode == SAIDA_SUCESSO, processo.stderr.decode()
    assert processo.stderr == b""
    envelope = json.loads(processo.stdout)
    assert envelope["status"] == "sucesso"
    # O oráculo é o total que a T-032 congelou, independente desta fixture.
    assert envelope["resultado"]["totais"]["baseline"] == 508382.32
    assert envelope["resultado"] == ESPERADO


def test_resultado_da_referencia_valida_no_schema_do_contrato(imagem: str) -> None:
    processo = rodar(imagem, entrada=bytes_do(payload(FONTE, ("2025-11",))))
    resultado = json.loads(processo.stdout)["resultado"]

    validacao = validar_no_contrato(com_orcamento(resultado))

    assert validacao.returncode == 0, validacao.stderr


def test_reexecutar_a_referencia_da_a_mesma_saida(imagem: str) -> None:
    entrada = bytes_do(payload(FONTE, ("2025-11",)))

    primeira = rodar(imagem, entrada=entrada)
    segunda = rodar(imagem, entrada=entrada)

    assert primeira.stdout == segunda.stdout
