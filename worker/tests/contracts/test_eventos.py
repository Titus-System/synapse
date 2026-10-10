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


# ---- a meta de venda e o propósito (T-270) ----


def test_desserializa_exemplo_executar_codigo_na_meta() -> None:
    mensagem = ExecutarCodigo.model_validate(carregar_exemplo("executar-codigo-meta-venda.json"))

    assert (mensagem.meta_venda, mensagem.proposito) == (26000000.0, "simulacao")


def test_desserializa_exemplo_executar_codigo_da_busca_da_meta() -> None:
    mensagem = ExecutarCodigo.model_validate(carregar_exemplo("executar-codigo-busca-meta.json"))

    assert (mensagem.meta_venda, mensagem.proposito) == (28500000.0, "busca_meta")


def test_sem_meta_o_comando_e_o_de_antes_da_meta() -> None:
    mensagem = ExecutarCodigo.model_validate(carregar_exemplo("executar-codigo.json"))

    assert (mensagem.meta_venda, mensagem.proposito) == (None, "simulacao")


@pytest.mark.parametrize(
    "mudanca",
    [
        {"meta_venda": None},
        {"meta_venda": 0.0},
        {"meta_venda": -1.0},
        {"proposito": "outro"},
        {"proposito": None},
    ],
    ids=["meta nula", "meta zero", "meta negativa", "proposito desconhecido", "proposito nulo"],
)
def test_meta_e_proposito_fora_do_contrato_sao_recusados(mudanca: dict[str, object]) -> None:
    """Só a ausência de `meta_venda` é uma execução sobre as vendas históricas: um `null` faria o
    worker simular nas vendas históricas uma execução pedida na meta."""
    comando = carregar_exemplo("executar-codigo-meta-venda.json") | mudanca

    with pytest.raises(ValidationError):
        ExecutarCodigo.model_validate_json(json.dumps(comando))


def test_meta_nao_finita_e_recusada() -> None:
    corpo = json.dumps(carregar_exemplo("executar-codigo-meta-venda.json")).replace(
        "26000000.0", "Infinity"
    )

    with pytest.raises(ValidationError, match="finite_number"):
        ExecutarCodigo.model_validate_json(corpo)


@pytest.mark.parametrize(
    "nome", ["simulacao-concluida-meta-venda.json", "simulacao-concluida-busca-meta.json"]
)
def test_simulacao_concluida_na_meta_sai_como_o_exemplo(nome: str) -> None:
    exemplo = carregar_exemplo(nome)

    mensagem = SimulacaoConcluida.model_validate(exemplo)

    assert mensagem.meta_venda == exemplo["meta_venda"]
    assert json.loads(mensagem.model_dump_json(exclude_none=True)) == exemplo
