from pathlib import Path
from shutil import copyfile

import pytest
import simplejson

from app.prompts import geracao_codigo
from app.representacao_regra import RepresentacaoRegra
from scripts.preparar_contexto_prompt import (
    preparar_contexto_prompt,
    preparar_contrato_regrafn,
    preparar_schemas_regra,
)

COMPONENTE = Path(__file__).resolve().parents[2]
CANONICO = COMPONENTE.parent / "worker" / "sandbox" / "data" / "domrock"
RECURSO = COMPONENTE / "app" / "prompts" / "contexto_bases.json"


def test_recurso_versionado_tem_somente_dez_linhas_canonicas_por_base() -> None:
    contexto = simplejson.loads(RECURSO.read_bytes(), use_decimal=True)

    assert set(contexto) == {"rh", "vendas", "comissoes", "eventos_rh"}
    for base, conteudo in contexto.items():
        assert set(conteudo) == {"esquema", "amostra"}
        assert len(conteudo["amostra"]) == 10
        with (CANONICO / f"{base}.jsonl").open(encoding="utf-8") as arquivo:
            registros = [simplejson.loads(linha, use_decimal=True) for linha in arquivo]
        for linha in conteudo["amostra"]:
            assert linha in registros


def test_preparacao_reproduz_bytes_versionados_em_duas_execucoes(tmp_path: Path) -> None:
    primeiro = tmp_path / "primeiro.json"
    segundo = tmp_path / "segundo.json"

    preparar_contexto_prompt(CANONICO, primeiro)
    preparar_contexto_prompt(CANONICO, segundo)

    assert primeiro.read_bytes() == segundo.read_bytes() == RECURSO.read_bytes()


def test_linhas_onze_em_diante_nao_vazam_da_preparacao_para_o_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copyfile(CANONICO / "schema.json", tmp_path / "schema.json")
    for base in ("rh", "vendas", "comissoes", "eventos_rh"):
        registros = [
            {
                "descr_marca": f"{base}_PERMITIDA_{indice}"
                if indice <= 10
                else f"{base}_SENTINELA_PROIBIDA_{indice}",
                "tipo": "ferias" if indice % 2 else "afastamento",
                "data_fim": None if indice % 2 else "2025-11-30",
                "detalhes": None if indice % 2 else {"motivo": "teste"},
                "cod_marca": 10 if indice % 2 else 20,
                "cod_cargo": 150,
                "descr_cargo": "GERENTE DE LOJA" if indice % 2 else "GERENTE QUIOSQUE",
                "data_venda": None if indice % 2 else "2025-11-24",
            }
            for indice in range(1, 14)
        ]
        (tmp_path / f"{base}.jsonl").write_text(
            "\n".join(simplejson.dumps(r) for r in registros), encoding="utf-8"
        )
    recurso = tmp_path / "contexto.json"
    preparar_contexto_prompt(tmp_path, recurso)
    monkeypatch.setattr(geracao_codigo, "_RECURSO", recurso)

    prompt = geracao_codigo.montar_prompt_geracao(
        RepresentacaoRegra.model_validate({"nucleo": {}, "especificacoes": []})
    )

    assert "SENTINELA_PROIBIDA" not in prompt
    assert "SENTINELA_PROIBIDA" not in recurso.read_text(encoding="utf-8")
    for base in ("rh", "vendas", "comissoes", "eventos_rh"):
        for indice in range(1, 11):
            assert f'"{base}_PERMITIDA_{indice}"' in prompt


def test_preparacao_recusa_base_menor_que_dez_sem_publicar_recurso(tmp_path: Path) -> None:
    copyfile(CANONICO / "schema.json", tmp_path / "schema.json")
    for base in ("rh", "vendas", "comissoes", "eventos_rh"):
        with (CANONICO / f"{base}.jsonl").open(encoding="utf-8") as arquivo:
            nove = [next(arquivo) for _ in range(9)]
        (tmp_path / f"{base}.jsonl").write_text("".join(nove), encoding="utf-8")
    destino = tmp_path / "contexto.json"

    with pytest.raises(ValueError, match="rh precisa conter pelo menos 10 registros"):
        preparar_contexto_prompt(tmp_path, destino)

    assert not destino.exists()


def test_preparacao_regrafn_reproduz_recurso_da_fonte_canonica(tmp_path: Path) -> None:
    fonte = COMPONENTE.parent / "contracts" / "harness" / "README.md"
    primeiro, segundo = tmp_path / "primeiro.md", tmp_path / "segundo.md"

    preparar_contrato_regrafn(fonte, primeiro)
    preparar_contrato_regrafn(fonte, segundo)

    assert (
        primeiro.read_bytes()
        == segundo.read_bytes()
        == (COMPONENTE / "app" / "prompts" / "regrafn.md").read_bytes()
    )


def test_preparacao_schemas_regra_reproduz_recurso_da_fonte_canonica(tmp_path: Path) -> None:
    fonte = COMPONENTE.parent / "contracts" / "domain"
    primeiro, segundo = tmp_path / "primeiro.json", tmp_path / "segundo.json"

    preparar_schemas_regra(fonte, primeiro)
    preparar_schemas_regra(fonte, segundo)

    assert (
        primeiro.read_bytes()
        == segundo.read_bytes()
        == (COMPONENTE / "app" / "prompts" / "regra_schemas.json").read_bytes()
    )


def test_recorte_do_contrato_falha_quando_a_fonte_perde_uma_secao(tmp_path: Path) -> None:
    fonte = COMPONENTE.parent / "contracts" / "harness" / "README.md"
    mutilada = tmp_path / "README.md"
    mutilada.write_text(
        fonte.read_text(encoding="utf-8").replace(
            "## Convenção de tipos das colunas", "## Outra coisa"
        ),
        encoding="utf-8",
    )
    destino = tmp_path / "regrafn.md"

    with pytest.raises(ValueError, match="Convenção de tipos das colunas"):
        preparar_contrato_regrafn(mutilada, destino)

    assert not destino.exists()
