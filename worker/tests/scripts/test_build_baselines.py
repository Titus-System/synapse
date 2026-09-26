import json
import os
import subprocess
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from app.sandbox.assercoes import AssercaoVioladaError
from scripts.build_baselines import (
    COMPETENCIAS,
    DATA_DIR,
    WORKER_ROOT,
    build_baselines,
    gerar_artefatos,
    ler_eventos_fonte,
)


@pytest.fixture(scope="module")
def artefatos() -> dict[str, bytes]:
    return gerar_artefatos()


def test_cinco_baselines_versionados_reproduzem_exatamente_os_bytes(
    artefatos: dict[str, bytes],
) -> None:
    nomes = [nome for nome in artefatos if nome.endswith(".jsonl") and "baseline-" in nome]
    assert nomes == [
        item
        for competencia in COMPETENCIAS
        for item in (
            f"baselines/baseline-{competencia}.jsonl",
            f"baselines/auditoria/baseline-{competencia}.jsonl",
        )
    ]
    for nome, conteudo in artefatos.items():
        assert (DATA_DIR / nome).read_bytes() == conteudo, nome
    manifesto = json.loads(artefatos["baselines/manifesto.json"])
    assert "Baseline não é gabarito" in manifesto["aviso"]


@pytest.mark.parametrize("competencia", COMPETENCIAS)
def test_total_lojas_e_matriculas_conciliam_em_centavos_e_tres_assercoes_passam(
    competencia: str,
    artefatos: dict[str, bytes],
) -> None:
    baseline = [
        json.loads(linha, parse_float=Decimal)
        for linha in artefatos[f"baselines/baseline-{competencia}.jsonl"].splitlines()
    ]
    registros = [
        json.loads(linha, parse_float=Decimal)
        for linha in artefatos[f"baselines/auditoria/baseline-{competencia}.jsonl"].splitlines()
    ]
    totais = [r for r in registros if r["nivel"] == "total"]
    lojas = [r for r in registros if r["nivel"] == "loja"]
    matriculas = [r for r in registros if r["nivel"] == "matricula"]
    assert len(baseline) == len(matriculas)
    assert {tuple(r) for r in baseline} == {
        ("cod_cargo", "cod_loja", "cod_marca", "comissao", "competencia", "matricula")
    }
    assert len(totais) == 1
    assert {r["competencia"] for r in registros} == {competencia}
    assert len({r["matricula"] for r in matriculas}) == len(matriculas)
    total = totais[0]["comissao"]
    assert sum((r["comissao"] for r in baseline), Decimal(0)) == total
    assert {r["matricula"]: r["comissao"] for r in baseline} == {
        r["matricula"]: r["comissao"] for r in matriculas
    }
    assert sum((r["comissao"] for r in lojas), Decimal(0)) == total
    assert sum((r["comissao"] for r in matriculas), Decimal(0)) == total
    por_loja: dict[int, Decimal] = defaultdict(Decimal)
    for linha in matriculas:
        assert linha["comissao"] >= 0
        por_loja[linha["cod_loja"]] += linha["comissao"]
    assert por_loja == {r["cod_loja"]: r["comissao"] for r in lojas}
    assert [a["nome"] for a in totais[0]["assercoes"]] == [
        "sem_comissao_negativa",
        "sem_comissao_sem_venda",
        "soma_loja_igual_soma_matricula",
    ]
    assert all(a["resultado"] == "ok" and a["detalhe"] is None for a in totais[0]["assercoes"])


def test_novembro_tem_black_friday_e_adicional_gerente_rastreaveis(
    artefatos: dict[str, bytes],
) -> None:
    linhas = [
        json.loads(linha)
        for linha in artefatos["baselines/auditoria/baseline-2025-11.jsonl"].splitlines()
    ]
    afetados: dict[str, list[dict[str, object]]] = {"NOV-5f": [], "NOV-5g": []}
    for linha in linhas:
        if linha["nivel"] != "matricula":
            continue
        for identificador in linha["rastreabilidade"].get("regras_competencia", []):
            afetados[identificador].append(linha)
    assert afetados["NOV-5f"] and afetados["NOV-5g"]
    assert all(r["cargo"] != 150 for r in afetados["NOV-5f"])
    assert all(r["cargo"] == 150 for r in afetados["NOV-5g"])


def test_reexecucoes_em_processos_com_hash_seeds_distintos_sao_identicas(tmp_path: Path) -> None:
    for seed in ("1", "777"):
        subprocess.run(
            [sys.executable, "-m", "scripts.build_baselines", "--output-dir", str(tmp_path / seed)],
            cwd=WORKER_ROOT,
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
            capture_output=True,
            text=True,
        )
    arquivos = sorted(
        p.relative_to(tmp_path / "1") for p in (tmp_path / "1").rglob("*") if p.is_file()
    )
    assert arquivos
    for nome in arquivos:
        assert (tmp_path / "1" / nome).read_bytes() == (tmp_path / "777" / nome).read_bytes()


def test_eventos_multiline_e_comentarios_preservam_valores_e_textos(tmp_path: Path) -> None:
    fonte = tmp_path / "eventos.jsonl"
    fonte.write_text(
        """// comentário
    {"id":"A","tipo":"ferias","matricula":"M","competencia_origem":"2025-12",
     "data_inicio":"2025-12-02","data_fim":"2025-12-15",
     "detalhes":{"fonte":"https://exemplo.test/a/*b*/"}}
    /* comentário de
       duas linhas */
    {"id":"B","tipo":"demissao","matricula":"N","competencia_origem":"2025-12",
     "data_inicio":"2025-12-10","data_fim":null,"detalhes":null}
    """,
        encoding="utf-8",
    )
    eventos = ler_eventos_fonte(fonte)
    assert eventos == [
        {
            "id": "A",
            "tipo": "ferias",
            "matricula": "M",
            "competencia_origem": "2025-12",
            "data_inicio": "2025-12-02",
            "data_fim": "2025-12-15",
            "detalhes": {"fonte": "https://exemplo.test/a/*b*/"},
        },
        {
            "id": "B",
            "tipo": "demissao",
            "matricula": "N",
            "competencia_origem": "2025-12",
            "data_inicio": "2025-12-10",
            "data_fim": None,
            "detalhes": None,
        },
    ]


def test_congelamento_impede_sobrescrita_silenciosa_e_check_nao_escreve(
    tmp_path: Path,
    artefatos: dict[str, bytes],
) -> None:
    for nome, dados in artefatos.items():
        destino = tmp_path / nome
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dados)
    alvo = tmp_path / "baselines/baseline-2025-11.jsonl"
    alvo.write_bytes(b"alterado\n")
    for check in (False, True):
        with pytest.raises(ValueError, match="congelado ausente/divergente"):
            build_baselines(output_dir=tmp_path, check=check)
        assert alvo.read_bytes() == b"alterado\n"


def test_falha_do_motor_nao_grava_nenhum_baseline(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    saida = tmp_path / "saida"
    entrada.mkdir()
    for nome in [
        "rh.jsonl",
        "vendas.jsonl",
        "comissoes.jsonl",
        "schema.json",
        "normalization_report.json",
        "regras_competencia.jsonl",
    ]:
        (entrada / nome).write_bytes((DATA_DIR / nome).read_bytes())
    taxas = [json.loads(linha) for linha in (entrada / "comissoes.jsonl").read_bytes().splitlines()]
    for taxa in taxas:
        if (
            taxa["competencia"] == "2025-08"
            and taxa["cod_marca"] == 10
            and taxa["cod_cargo"] == 100
        ):
            taxa["percentual_comissao"] = -1
    (entrada / "comissoes.jsonl").write_text(
        "\n".join(json.dumps(t) for t in taxas) + "\n", encoding="utf-8"
    )
    with pytest.raises(AssercaoVioladaError, match="sem_comissao_negativa"):
        build_baselines(data_dir=entrada, output_dir=saida)
    assert not saida.exists()


def test_multiplas_marcas_na_mesma_matricula_falham_antes_do_congelamento() -> None:
    from scripts.build_baselines import _marca_unica_da_rastreabilidade

    linha = {
        "matricula": "MATRIC-X",
        "rastreabilidade": {"chaves_comissao": [{"cod_marca": 10}, {"cod_marca": 20}]},
    }
    with pytest.raises(ValueError, match="exatamente uma cod_marca"):
        _marca_unica_da_rastreabilidade(linha, "2025-11")


@pytest.mark.parametrize(
    ("marcas", "mensagem"),
    [((10, 20), "exatamente uma cod_marca"), ((20,), "difere do RH")],
)
def test_build_recusa_marca_ambigua_ou_divergente_sem_gravar_artefatos(
    tmp_path: Path, marcas: tuple[int, ...], mensagem: str
) -> None:
    entrada, saida = tmp_path / "entrada", tmp_path / "saida"
    entrada.mkdir()
    for nome in ("schema.json", "normalization_report.json"):
        (entrada / nome).write_bytes((DATA_DIR / nome).read_bytes())
    pessoa = {
        "competencia": "2025-08",
        "matricula": "MATRIC-TESTE",
        "cod_loja": 1,
        "descr_loja": "LOJA-1",
        "cod_marca": 10,
        "cod_cargo": 100,
        "data_admiss": "2020-01-01",
        "data_demiss": None,
    }
    vendas = [
        {
            "competencia": "2025-08",
            "data_ref": "2025-08-01",
            "matricula": "MATRIC-TESTE",
            "cod_loja": 1,
            "cod_marca": marca,
            "vlr_venda": 1000.0,
        }
        for marca in marcas
    ]
    (entrada / "rh.jsonl").write_text(json.dumps(pessoa) + "\n", encoding="utf-8")
    (entrada / "vendas.jsonl").write_text(
        "\n".join(json.dumps(venda) for venda in vendas) + "\n", encoding="utf-8"
    )
    (entrada / "comissoes.jsonl").write_bytes((DATA_DIR / "comissoes.jsonl").read_bytes())
    (entrada / "regras_competencia.jsonl").write_bytes(
        (DATA_DIR / "regras_competencia.jsonl").read_bytes()
    )
    eventos = entrada / "eventos_fonte.jsonl"
    eventos.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match=mensagem):
        build_baselines(data_dir=entrada, eventos_fonte=eventos, output_dir=saida)

    assert not saida.exists()


def test_schema_anota_os_mesmos_campos_do_baseline(artefatos: dict[str, bytes]) -> None:
    schema = json.loads((DATA_DIR / "schema.json").read_bytes())
    for tabela, caminho in (
        ("baseline", "baselines/baseline-{competencia}.jsonl"),
        ("baseline_auditoria", "baselines/auditoria/baseline-{competencia}.jsonl"),
    ):
        colunas = {campo["name"] for campo in schema["tables"][tabela]["fields"]}
        for competencia in COMPETENCIAS:
            for linha in artefatos[caminho.format(competencia=competencia)].splitlines():
                assert set(json.loads(linha)) == colunas
