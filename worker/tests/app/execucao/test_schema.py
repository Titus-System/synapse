"""A validação do resultado pelo schema da T-034, e o que acontece sem `contracts/`."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from app import main
from app.execucao import schema
from app.execucao.schema import (
    ContratosIndisponiveisError,
    carregar_contratos,
    validador,
    validar_assercoes,
    validar_resultado,
)
from tests.app.execucao.envelopes import ASSERCAO_OK, ASSERCAO_VIOLADA, ORCAMENTO, RESULTADO

CAMINHO_DO_MODULO = Path(schema.__file__)


def test_o_schema_exige_o_orcamento_que_o_container_nao_tem() -> None:
    """A razão de o worker acrescentar `totais.orcamento` antes de validar: o schema o exige
    e a saída do container nunca o traz."""
    erros = [e.validator for e in validador().iter_errors(RESULTADO)]

    assert "required" in erros


def test_o_resultado_do_container_valida_com_o_orcamento_do_worker() -> None:
    assert validar_resultado(RESULTADO, ORCAMENTO) == []


def test_a_validacao_nao_altera_o_resultado() -> None:
    antes = {**RESULTADO, "totais": dict(RESULTADO["totais"])}

    validar_resultado(RESULTADO, ORCAMENTO)

    assert antes == RESULTADO
    assert "orcamento" not in RESULTADO["totais"]


def test_totais_que_nao_e_objeto_e_reprovado_sem_levantar() -> None:
    assert validar_resultado({**RESULTADO, "totais": 1}, ORCAMENTO) == ["$.totais: type"]


def test_as_cinco_quebras_sao_exigidas() -> None:
    for quebra in RESULTADO["decomposicao"]:
        decomposicao = {k: v for k, v in RESULTADO["decomposicao"].items() if k != quebra}

        erros = validar_resultado({**RESULTADO, "decomposicao": decomposicao}, ORCAMENTO)

        assert erros == ["$.decomposicao: required"], quebra


def test_desfechos_de_assercao() -> None:
    assert validar_assercoes([ASSERCAO_OK, ASSERCAO_VIOLADA]) == []
    assert validar_assercoes([{"nome": "x", "resultado": "talvez", "detalhe": None}]) == [
        "$[0].resultado: enum"
    ]
    assert validar_assercoes("ok") == [": type".replace(":", "$:", 1)]


def test_carregar_contratos_funciona_no_repositorio() -> None:
    carregar_contratos()


def test_sem_contracts_o_carregamento_falha_alto(tmp_path: Path) -> None:
    """Numa imagem montada sem `contracts/`, o processo tem de cair na subida, e não deixar o
    primeiro job descobrir. O módulo é copiado para uma árvore sem `contracts/` acima dele."""
    pasta = tmp_path / "app" / "execucao"
    pasta.mkdir(parents=True)
    (pasta / "schema.py").write_text(CAMINHO_DO_MODULO.read_text(encoding="utf-8"))

    resultado = subprocess.run(
        [sys.executable, "-c", "import schema; schema.carregar_contratos()"],
        cwd=pasta,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert resultado.returncode != 0
    assert "ContratosIndisponiveisError" in resultado.stderr


async def test_a_subida_do_worker_carrega_os_contratos_antes_de_ligar_o_consumidor(
    monkeypatch: pytest.MonkeyPatch, api: FastAPI
) -> None:
    conectar = AsyncMock()
    monkeypatch.setattr(main, "verificar_acesso", AsyncMock())
    monkeypatch.setattr(main, "conectar", conectar)
    monkeypatch.setattr(
        main,
        "carregar_contratos",
        lambda: (_ for _ in ()).throw(ContratosIndisponiveisError("sem contracts")),
    )

    with pytest.raises(ContratosIndisponiveisError):
        async with main.lifespan(api):
            pytest.fail("o worker não pode subir sem os contratos")

    conectar.assert_not_awaited()
