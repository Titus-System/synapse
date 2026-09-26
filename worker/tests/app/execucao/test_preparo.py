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
