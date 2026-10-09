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
    # O comando de antes da conferência de cobertura (T-241): o worker não a faz.
    assert mensagem.elementos_exigidos is None


def test_desserializa_exemplo_executar_codigo_com_elementos_exigidos() -> None:
    mensagem = ExecutarCodigo.model_validate(carregar_exemplo("executar-codigo-cobertura.json"))

    assert mensagem.elementos_exigidos == ["nucleo.percentual", "elem.1"]


def test_desserializa_exemplo_simulacao_concluida() -> None:
    mensagem = SimulacaoConcluida.model_validate(carregar_exemplo("simulacao-concluida.json"))

    assert mensagem.status == "sucesso"
    assert mensagem.veredito == "inviavel"
    assert mensagem.total_simulado == 492100.0
