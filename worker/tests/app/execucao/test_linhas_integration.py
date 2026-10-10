"""O envelope sai da imagem real com os limites de produção (T-259)."""

import json
from dataclasses import replace

import pytest
from httpx import AsyncClient
from prometheus_client import REGISTRY

from app.execucao.coleta import classificar
from app.execucao.container import Limites, executar_no_sandbox
from tests.app.execucao.envelopes import PAYLOAD
from tests.app.sandbox.detalhamento import (
    COMPETENCIAS,
    REGRA_TRES_ELEMENTOS,
    envelope_do_periodo,
)

pytestmark = pytest.mark.docker


@pytest.mark.parametrize("status", ["sucesso", "erro_codigo"])
async def test_envelope_real_e_medido_e_exposto_em_metrics(
    imagem: str,
    client: AsyncClient,
    status: str,
) -> None:
    fonte = (
        REGRA_TRES_ELEMENTOS
        if status == "sucesso"
        else "def aplicar_regra(b, a, c):\n    raise ValueError('falha controlada')\n"
    )
    payload = replace(PAYLOAD, fonte=fonte, competencias=COMPETENCIAS)
    labels = {"status": status}
    antes = REGISTRY.get_sample_value("sandbox_envelope_bytes_count", labels) or 0
    saida = executar_no_sandbox(payload, imagem=imagem)

    desfecho = classificar(saida, payload, None)

    assert desfecho.classe == status
    assert not saida.stdout_truncado
    assert len(saida.stdout) < Limites().teto_stdout * 0.8
    assert REGISTRY.get_sample_value("sandbox_envelope_bytes_count", labels) == antes + 1
    resposta = await client.get("/metrics")
    assert f'sandbox_envelope_bytes_count{{status="{status}"}} {antes + 1}' in resposta.text
    if status == "sucesso":
        assert desfecho.linhas == envelope_do_periodo()["linhas"]
        assert desfecho.resultado == envelope_do_periodo()["resultado"]
        assert desfecho.linhas == json.loads(saida.stdout)["linhas"]
    else:
        assert desfecho.linhas is None
