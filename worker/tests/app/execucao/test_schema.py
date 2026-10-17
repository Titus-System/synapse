"""A validação do resultado pelo schema da T-034, e o que acontece sem `contracts/`."""

import json
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
    validar_diagnostico,
    validar_resultado,
)
from tests.app.execucao.envelopes import ASSERCAO_OK, ASSERCAO_VIOLADA, ORCAMENTO, RESULTADO

CAMINHO_DO_MODULO = Path(schema.__file__)
EXEMPLOS_DE_DIAGNOSTICO = sorted(
    (Path(__file__).resolve().parents[4] / "contracts" / "examples" / "domain").glob(
        "resultado-diagnostico-*.json"
    )
)


def test_o_schema_aceita_totais_sem_orcamento() -> None:
    """Job sem orçamento é simulado sem a verificação de orçamento (T-269): o schema não exige
    `totais.orcamento`, e quem o acrescenta, quando o comando o traz, é o worker."""
    assert list(validador().iter_errors(RESULTADO)) == []


def test_o_resultado_do_container_valida_com_o_orcamento_do_worker() -> None:
    assert validar_resultado(RESULTADO, ORCAMENTO) == []


def test_a_validacao_nao_altera_o_resultado() -> None:
    antes = {**RESULTADO, "totais": dict(RESULTADO["totais"])}

    validar_resultado(RESULTADO, ORCAMENTO)

    assert antes == RESULTADO
    assert "orcamento" not in RESULTADO["totais"]


def test_totais_que_nao_e_objeto_e_reprovado_sem_levantar() -> None:
    assert validar_resultado({**RESULTADO, "totais": 1}, ORCAMENTO) == [
        {"caminho": "$.totais", "palavra_chave": "type"}
    ]


def test_as_cinco_quebras_sao_exigidas() -> None:
    for quebra in RESULTADO["decomposicao"]:
        decomposicao = {k: v for k, v in RESULTADO["decomposicao"].items() if k != quebra}

        erros = validar_resultado({**RESULTADO, "decomposicao": decomposicao}, ORCAMENTO)

        assert erros == [{"caminho": "$.decomposicao", "palavra_chave": "required"}], quebra


def test_desfechos_de_assercao() -> None:
    assert validar_assercoes([ASSERCAO_OK, ASSERCAO_VIOLADA]) == []
    assert validar_assercoes([{"nome": "x", "resultado": "talvez", "detalhe": None}]) == [
        {"caminho": "$[0].resultado", "palavra_chave": "enum"}
    ]
    assert validar_assercoes("ok") == [{"caminho": "$", "palavra_chave": "type"}]


@pytest.mark.parametrize("exemplo", EXEMPLOS_DE_DIAGNOSTICO, ids=lambda caminho: caminho.stem)
def test_os_exemplos_de_diagnostico_do_contrato_validam(exemplo: Path) -> None:
    """Os exemplos são o que cada componente desserializa (ADR-002): se o worker os recusasse,
    ele e o contrato descreveriam coisas diferentes."""
    assert validar_diagnostico(json.loads(exemplo.read_text(encoding="utf-8"))) == []


def test_ha_exemplos_de_diagnostico_para_conferir() -> None:
    assert len(EXEMPLOS_DE_DIAGNOSTICO) >= 3


@pytest.mark.parametrize(
    ("diagnostico", "problema"),
    [
        ({}, {"caminho": "$", "palavra_chave": "required"}),
        ({"causa": "excecao"}, {"caminho": "$", "palavra_chave": "required"}),
        (
            {"causa": "timeout", "falha": {"tipo": "", "mensagem": "", "traceback": ""}},
            {"caminho": "$", "palavra_chave": "not"},
        ),
        ({"causa": "infra"}, {"caminho": "$.causa", "palavra_chave": "enum"}),
    ],
    ids=["sem causa", "excecao sem falha", "falha sem excecao", "causa desconhecida"],
)
def test_diagnostico_fora_do_contrato_e_reprovado(
    diagnostico: dict[str, object], problema: dict[str, str]
) -> None:
    assert problema in validar_diagnostico(diagnostico)


def test_carregar_contratos_funciona_no_repositorio() -> None:
    carregar_contratos()


def test_sem_contracts_o_carregamento_falha_alto(tmp_path: Path) -> None:
    """Numa imagem montada sem `contracts/`, o processo tem de cair na subida, e não deixar o
    primeiro job descobrir. O módulo é copiado para uma árvore sem `contracts/` acima dele."""
    pasta = tmp_path / "app" / "execucao"
    pasta.mkdir(parents=True)
    (pasta / "schema.py").write_text(
        CAMINHO_DO_MODULO.read_text(encoding="utf-8"), encoding="utf-8"
    )

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
