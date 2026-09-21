import json
from pathlib import Path

from app.mensageria.contracts import ExecutarCodigo, SimulacaoConcluida

CONTRACT_EXAMPLES = Path(__file__).resolve().parents[3] / "contracts" / "examples" / "events"


def carregar_exemplo(nome: str) -> dict[str, object]:
    with (CONTRACT_EXAMPLES / nome).open(encoding="utf-8") as arquivo:
        conteudo = json.load(arquivo)

    assert isinstance(conteudo, dict)
    return conteudo


def test_desserializa_exemplo_executar_codigo() -> None:
    mensagem = ExecutarCodigo.model_validate(carregar_exemplo("executar-codigo.json"))

    assert str(mensagem.job_id) == "3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021"
    assert mensagem.competencias == ["2025-08", "2025-11"]
    assert mensagem.orcamento == 485000.0


def test_desserializa_exemplo_simulacao_concluida() -> None:
    mensagem = SimulacaoConcluida.model_validate(carregar_exemplo("simulacao-concluida.json"))

    assert mensagem.status == "sucesso"
    assert mensagem.veredito == "inviavel"
    assert mensagem.total_simulado == 492100.0
