import json
from pathlib import Path

import pytest
from pydantic import ValidationError

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


def test_desserializa_exemplo_executar_codigo_sem_orcamento() -> None:
    """Job sem orçamento (T-281): o comando chega sem o campo, e o worker o aceita."""
    mensagem = ExecutarCodigo.model_validate(carregar_exemplo("executar-codigo-sem-orcamento.json"))

    assert mensagem.orcamento is None
    assert mensagem.elementos_exigidos == ["nucleo.percentual", "elem.1"]


def test_orcamento_negativo_continua_recusado() -> None:
    with pytest.raises(ValidationError):
        ExecutarCodigo.model_validate(
            carregar_exemplo("executar-codigo.json") | {"orcamento": -1.0}
        )


def test_simulacao_concluida_sem_orcamento_sai_sem_veredito_como_o_exemplo() -> None:
    """O sucesso de job sem orçamento não tem veredito, e o campo fica ausente, não `null`."""
    exemplo = carregar_exemplo("simulacao-concluida-sem-orcamento.json")

    mensagem = SimulacaoConcluida.model_validate(exemplo)

    assert (mensagem.status, mensagem.veredito) == ("sucesso", None)
    assert json.loads(mensagem.model_dump_json(exclude_none=True)) == exemplo


def test_orcamento_nulo_e_recusado_e_so_a_ausencia_e_job_sem_orcamento() -> None:
    sem_campo = carregar_exemplo("executar-codigo-sem-orcamento.json")

    assert ExecutarCodigo.model_validate(sem_campo).orcamento is None
    with pytest.raises(ValidationError):
        ExecutarCodigo.model_validate(sem_campo | {"orcamento": None})
    with pytest.raises(ValidationError):
        ExecutarCodigo.model_validate_json(json.dumps(sem_campo | {"orcamento": None}))
