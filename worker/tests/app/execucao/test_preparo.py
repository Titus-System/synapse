from uuid import uuid4

from app.execucao.preparo import preparar_execucao
from app.mensageria.contracts import ExecutarCodigo
from app.repositorio.codigos_gerados import CodigoGerado


def _comando(**overrides: object) -> ExecutarCodigo:
    dados: dict[str, object] = {
        "job_id": uuid4(),
        "codigo_gerado_id": uuid4(),
        "competencias": ["2025-08", "2025-11"],
        "orcamento": 485000.0,
    }
    dados.update(overrides)
    return ExecutarCodigo.model_validate(dados)


def _codigo(**overrides: object) -> CodigoGerado:
    dados: dict[str, object] = {
        "id": uuid4(),
        "job_id": uuid4(),
        "linguagem": "python",
        "fonte": "def executar(): ...",
    }
    dados.update(overrides)
    return CodigoGerado.model_validate(dados)


def test_payload_do_container_nao_inclui_orcamento() -> None:
    codigo = _codigo()
    comando = _comando(codigo_gerado_id=codigo.id)

    execucao = preparar_execucao(comando, codigo)

    assert not hasattr(execucao.payload, "orcamento")
    assert execucao.orcamento == comando.orcamento


def test_payload_carrega_fonte_e_competencias_do_codigo_e_do_comando() -> None:
    codigo = _codigo(fonte="def executar(): return 1")
    comando = _comando(codigo_gerado_id=codigo.id, competencias=["2025-01"])

    execucao = preparar_execucao(comando, codigo)

    assert execucao.payload.fonte == "def executar(): return 1"
    assert execucao.payload.linguagem == "python"
    assert execucao.payload.competencias == ["2025-01"]
    assert execucao.payload.codigo_gerado_id == codigo.id
    assert execucao.payload.job_id == comando.job_id


def test_comando_sem_orcamento_prepara_a_execucao_sem_ele() -> None:
    """Job sem orçamento (T-281): nada muda no que entra no container, e o julgamento recebe a
    ausência para não emitir veredito."""
    codigo = _codigo()
    comando = ExecutarCodigo.model_validate(
        {"job_id": uuid4(), "codigo_gerado_id": codigo.id, "competencias": ["2025-08"]}
    )

    execucao = preparar_execucao(comando, codigo)

    assert execucao.orcamento is None
    assert not hasattr(execucao.payload, "orcamento")
    assert execucao.payload.competencias == ["2025-08"]


def test_a_meta_vai_ao_container_e_o_proposito_nao() -> None:
    """A meta muda a entrada da apuração e entra no payload; o propósito não muda a execução e
    fica com o worker, que o grava e o devolve (T-270)."""
    codigo = _codigo()
    comando = _comando(codigo_gerado_id=codigo.id, meta_venda=26000000.0, proposito="busca_meta")

    execucao = preparar_execucao(comando, codigo)

    assert execucao.payload.meta_venda == 26000000.0
    assert not hasattr(execucao.payload, "proposito")
    assert execucao.proposito == "busca_meta"


def test_sem_meta_o_payload_vai_sem_meta_e_o_proposito_e_simulacao() -> None:
    codigo = _codigo()

    execucao = preparar_execucao(_comando(codigo_gerado_id=codigo.id), codigo)

    assert execucao.payload.meta_venda is None
    assert execucao.proposito == "simulacao"
