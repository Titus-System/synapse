"""Os motivos T-224 partilham o registry exportado por /metrics."""

import json
import logging
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from app.core.logger import FormatadorJson
from app.core.metrics.global_metrics import MOTIVOS_DE_REBAIXAMENTO, rebaixamentos_extracao
from app.core.metrics.prometheus import prometheus


def test_motivos_da_t224_constam_da_familia_publicada() -> None:
    assert {"operacao_sem_trecho", "valor_sem_lastro"} <= set(MOTIVOS_DE_REBAIXAMENTO)
    assert len(MOTIVOS_DE_REBAIXAMENTO) == len(set(MOTIVOS_DE_REBAIXAMENTO))

    for motivo in ("operacao_sem_trecho", "valor_sem_lastro"):
        antes = rebaixamentos_extracao.labels(motivo=motivo)._value.get()
        rebaixamentos_extracao.labels(motivo=motivo).inc()
        depois = prometheus.get_all().decode("utf-8")

        assert rebaixamentos_extracao.labels(motivo=motivo)._value.get() - antes == 1
        assert f'motivo="{motivo}"' in depois
        assert "codegen_extracao_rebaixamentos_total" in depois


def test_log_operacional_respeita_schema_sem_conteudo_da_correcao() -> None:
    arquivo = Path(__file__).resolve().parents[4] / "contracts/observability/log.schema.json"
    contrato = json.loads(arquivo.read_text(encoding="utf-8"))
    registro = logging.LogRecord(
        "app.graph.nodes.reextract_rule",
        logging.INFO,
        __file__,
        1,
        "reextraction finished",
        (),
        None,
    )
    registro.quantidade_rebaixamentos = 2
    registro.rebaixamentos_por_motivo = {"operacao_sem_trecho": 1, "valor_sem_lastro": 1}
    log = json.loads(FormatadorJson().format(registro))

    Draft202012Validator(contrato, format_checker=FormatChecker()).validate(log)
    serializado = json.dumps(log, ensure_ascii=False)
    assert "TEXTO_CORRECAO_PRIVADA" not in serializado
    assert "HISTORICO_CORRECOES_PRIVADO" not in serializado
    assert log["extra"]["rebaixamentos_por_motivo"] == {
        "operacao_sem_trecho": 1,
        "valor_sem_lastro": 1,
    }
