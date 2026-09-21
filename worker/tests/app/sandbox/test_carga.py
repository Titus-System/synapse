import json
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest

from app.sandbox.carga import (
    COLUNAS,
    RAIZ_DADOS,
    TABELAS,
    BaseInconsistenteError,
    CargaError,
    CompetenciaNaoPublicadaError,
    Tipo,
    carregar,
    competencias_publicadas,
    ler_jsonl,
)

COMPETENCIAS = ("2025-08", "2025-09", "2025-10", "2025-11", "2025-12")
SCHEMA = json.loads((RAIZ_DADOS / "schema.json").read_text(encoding="utf-8"))

# Oráculo independente de COLUNAS: a tabela "Convenção de tipos das colunas" de
# contracts/harness/README.md, escrita à mão. Códigos e valores são numéricos; o resto
# fica em object, inclusive as datas (texto) e o objeto de detalhes.
DTYPES_DO_CONTRATO: Mapping[str, Mapping[str, str]] = {
    "rh": {"cod_marca": "int64", "cod_loja": "int64", "cod_cargo": "int64"},
    "vendas": {"cod_marca": "int64", "cod_loja": "int64", "vlr_venda": "float64"},
    "comissoes": {"cod_marca": "int64", "cod_cargo": "int64", "percentual_comissao": "float64"},
    "eventos_rh": {},
    "apuracao_base": {
        "cod_loja": "int64",
        "cod_marca": "int64",
        "cod_cargo": "int64",
        "comissao": "float64",
    },
}


def dtype_esperado(tabela: str, coluna: str) -> str:
    return DTYPES_DO_CONTRATO[tabela].get(coluna, "object")


# ---- dataset sintético: só para os caminhos de erro, o dado real cobre o resto ----


def linha_rh(
    matricula: str = "MATRIC-1",
    *,
    competencia: str = "2025-08",
    cod_marca: int = 10,
    cod_loja: int = 1,
    cod_cargo: int = 100,
) -> dict[str, object]:
    return {
        "competencia": competencia,
        "data_ref": f"{competencia}-01",
        "cod_marca": cod_marca,
        "descr_marca": "PRETO",
        "cod_loja": cod_loja,
        "descr_loja": f"LOJA-{cod_loja}",
        "matricula": matricula,
        "data_admiss": "2020-01-01",
        "data_demiss": None,
        "cod_cargo": cod_cargo,
        "descr_cargo": "VENDEDOR",
    }


def linha_baseline(
    matricula: str = "MATRIC-1",
    *,
    competencia: str = "2025-08",
    cod_loja: int = 1,
    cargo: int = 100,
    comissao: float = 100.0,
    marcas: Sequence[int] = (10,),
) -> dict[str, object]:
    return {
        "nivel": "matricula",
        "competencia": competencia,
        "matricula": matricula,
        "cod_loja": cod_loja,
        "loja": f"LOJA-{cod_loja}",
        "cargo": cargo,
        "base_calculo": 1000.0,
        "comissao": comissao,
        "assercoes": None,
        "rastreabilidade": {
            "chaves_comissao": [
                {"cod_cargo": cargo, "cod_marca": marca, "percentual_comissao": 0.025}
                for marca in marcas
            ]
        },
    }


def escrever_jsonl(caminho: Path, linhas: Sequence[Mapping[str, object]]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        "".join(json.dumps(linha, ensure_ascii=False) + "\n" for linha in linhas),
        encoding="utf-8",
    )


def escrever_dataset(
    raiz: Path,
    *,
    rh: Sequence[Mapping[str, object]] = (),
    vendas: Sequence[Mapping[str, object]] = (),
    comissoes: Sequence[Mapping[str, object]] = (),
    eventos: Sequence[Mapping[str, object]] = (),
    baselines: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
    publicadas: Sequence[str] = ("2025-08", "2025-09"),
    editar_manifesto: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    raiz.mkdir(parents=True, exist_ok=True)
    (raiz / "schema.json").write_text(
        json.dumps({"published_competencias": list(publicadas)}), encoding="utf-8"
    )
    escrever_jsonl(raiz / "rh.jsonl", rh)
    escrever_jsonl(raiz / "vendas.jsonl", vendas)
    escrever_jsonl(raiz / "comissoes.jsonl", comissoes)
    escrever_jsonl(raiz / "eventos_rh.jsonl", eventos)

    manifesto: dict[str, Any] = {"baselines": {}}
    for competencia in publicadas:
        linhas = list((baselines or {}).get(competencia, ()))
        arquivo = f"baselines/baseline-{competencia}.jsonl"
        escrever_jsonl(raiz / arquivo, linhas)
        total = sum(
            (Decimal(str(linha["comissao"])) for linha in linhas if linha["nivel"] == "matricula"),
            Decimal(0),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        manifesto["baselines"][competencia] = {
            "arquivo": arquivo,
            "matriculas": sum(linha["nivel"] == "matricula" for linha in linhas),
            "total": float(total),
        }
    if editar_manifesto:
        editar_manifesto(manifesto)
    (raiz / "baselines").mkdir(exist_ok=True)
    (raiz / "baselines" / "manifesto.json").write_text(json.dumps(manifesto), encoding="utf-8")
    return raiz


def dataset_de_um_funcionario(raiz: Path, **mudancas: Any) -> Path:
    base: dict[str, Any] = {
        "rh": [linha_rh()],
        "baselines": {"2025-08": [linha_baseline()]},
    }
    base.update(mudancas)
    return escrever_dataset(raiz, **base)


# ---- o mapa de tipos e o schema ----


def _tipo_do_schema(campo: Mapping[str, Any]) -> Tipo:
    tipo, anulavel = campo["type"], campo["nullable"]
    if tipo == "string":
        return Tipo.TEXTO_OPCIONAL if anulavel else Tipo.TEXTO
    if tipo == "integer":
        return Tipo.INTEIRO
    if tipo == "number":
        return Tipo.DECIMAL
    assert tipo == "object" and anulavel
    return Tipo.OBJETO_OPCIONAL


@pytest.mark.parametrize("tabela", TABELAS)
def test_mapa_de_tipos_cobre_exatamente_o_schema(tabela: str) -> None:
    campos = {campo["name"]: campo for campo in SCHEMA["tables"][tabela]["fields"]}

    assert list(COLUNAS[tabela]) == list(campos)
    assert {nome: _tipo_do_schema(campo) for nome, campo in campos.items()} == dict(COLUNAS[tabela])


def test_competencias_publicadas_sao_as_cinco_do_dataset() -> None:
    assert competencias_publicadas() == COMPETENCIAS


# ---- carga do dado real ----


@pytest.fixture(scope="module")
def novembro() -> Any:
    return carregar(["2025-11"])


@pytest.mark.parametrize("tabela", [*TABELAS, "apuracao_base"])
def test_dtypes_seguem_a_convencao_do_contrato(novembro: Any, tabela: str) -> None:
    dataframe = novembro.apuracao_base if tabela == "apuracao_base" else novembro.bases[tabela]

    assert {coluna: str(dtype) for coluna, dtype in dataframe.dtypes.items()} == {
        coluna: dtype_esperado(tabela, coluna) for coluna in dataframe.columns
    }


def test_bases_tem_exatamente_as_quatro_chaves_do_contrato(novembro: Any) -> None:
    assert set(novembro.bases) == {"rh", "vendas", "comissoes", "eventos_rh"}


@pytest.mark.parametrize("tabela", ["rh", "vendas", "comissoes"])
def test_recorta_ao_periodo_e_conta_como_o_arquivo(novembro: Any, tabela: str) -> None:
    esperado = [
        r for r in ler_jsonl(RAIZ_DADOS / f"{tabela}.jsonl") if r["competencia"] == "2025-11"
    ]

    assert set(novembro.bases[tabela]["competencia"]) == {"2025-11"}
    assert len(novembro.bases[tabela]) == len(esperado) > 0


def test_eventos_de_rh_chegam_inteiros_inclusive_de_julho(novembro: Any) -> None:
    eventos = ler_jsonl(RAIZ_DADOS / "eventos_rh.jsonl")

    assert len(novembro.bases["eventos_rh"]) == len(eventos)
    assert "2025-07" in set(novembro.bases["eventos_rh"]["competencia_origem"])


def test_nulos_de_texto_e_objeto_continuam_none(novembro: Any) -> None:
    demissao = list(novembro.bases["rh"]["data_demiss"])
    detalhes = list(novembro.bases["eventos_rh"]["detalhes"])

    assert any(valor is None for valor in demissao) and any(isinstance(v, str) for v in demissao)
    assert not any(valor == "None" for valor in demissao)
    assert any(valor is None for valor in detalhes) and any(isinstance(v, dict) for v in detalhes)


def test_venda_inteira_no_json_vira_float(novembro: Any) -> None:
    assert str(novembro.bases["vendas"]["vlr_venda"].dtype) == "float64"


@pytest.mark.parametrize("competencia", COMPETENCIAS)
def test_apuracao_base_reproduz_o_total_congelado_de_cada_competencia(competencia: str) -> None:
    """O oráculo é a linha ``total`` do próprio arquivo de baseline, que a T-032 calculou
    por um caminho diferente (o motor de regras), não a conversão que está sendo testada."""
    congelado = next(
        linha
        for linha in ler_jsonl(RAIZ_DADOS / "baselines" / f"baseline-{competencia}.jsonl")
        if linha["nivel"] == "total"
    )

    apuracao = carregar([competencia]).apuracao_base

    total = sum((Decimal(str(v)) for v in apuracao["comissao"]), Decimal(0))
    assert total == Decimal(str(congelado["comissao"]))


def test_apuracao_base_de_novembro_tem_a_forma_e_o_total_do_contrato(novembro: Any) -> None:
    apuracao = novembro.apuracao_base

    assert list(apuracao.columns) == list(COLUNAS["apuracao_base"])
    assert len(apuracao) == 546
    assert round(float(apuracao["comissao"].sum()), 2) == 508382.32
    assert set(apuracao["competencia"]) == {"2025-11"}


def test_cod_marca_do_baseline_e_o_do_rh(novembro: Any) -> None:
    marca_do_rh = dict(
        zip(novembro.bases["rh"]["matricula"], novembro.bases["rh"]["cod_marca"], strict=True)
    )

    assert all(
        marca_do_rh[matricula] == marca
        for matricula, marca in zip(
            novembro.apuracao_base["matricula"], novembro.apuracao_base["cod_marca"], strict=True
        )
    )


def test_periodo_de_varios_meses_preserva_a_ordem_recebida() -> None:
    entrada = carregar(["2025-10", "2025-08", "2025-09"])

    ordem = list(dict.fromkeys(entrada.apuracao_base["competencia"]))
    assert ordem == ["2025-10", "2025-08", "2025-09"]
    assert set(entrada.bases["rh"]["competencia"]) == {"2025-08", "2025-09", "2025-10"}


def test_registros_base_espelham_o_dataframe_em_tipos_nativos(novembro: Any) -> None:
    registros = novembro.registros_base

    assert len(registros) == len(novembro.apuracao_base)
    assert registros[0] == novembro.apuracao_base.iloc[0].to_dict() | {
        "cod_loja": registros[0]["cod_loja"]
    }
    assert type(registros[0]["cod_loja"]) is int
    assert type(registros[0]["comissao"]) is float


def test_carga_e_deterministica() -> None:
    primeira, segunda = carregar(["2025-11"]), carregar(["2025-11"])

    assert primeira.registros_base == segunda.registros_base
    for nome in TABELAS:
        assert primeira.bases[nome].equals(segunda.bases[nome])


# ---- período ----


@pytest.mark.parametrize(
    ("competencias", "erro"),
    [
        ([], CargaError),
        (["2025-11", "2025-11"], CargaError),
        (["2025-07"], CompetenciaNaoPublicadaError),
        (["2025-11", "2026-01"], CompetenciaNaoPublicadaError),
    ],
)
def test_periodo_invalido_e_recusado(competencias: list[str], erro: type[Exception]) -> None:
    with pytest.raises(erro):
        carregar(competencias)


def test_periodo_sem_nenhuma_linha_preserva_o_dtype_do_contrato(tmp_path: Path) -> None:
    raiz = dataset_de_um_funcionario(tmp_path)

    entrada = carregar(["2025-09"], raiz=raiz)

    assert len(entrada.bases["rh"]) == 0 and len(entrada.apuracao_base) == 0
    for tabela in TABELAS:
        assert {c: str(d) for c, d in entrada.bases[tabela].dtypes.items()} == {
            c: dtype_esperado(tabela, c) for c in entrada.bases[tabela].columns
        }
    assert str(entrada.apuracao_base["cod_marca"].dtype) == "int64"


# ---- dado embutido fora do contrato ----


def _sem_coluna(linhas: list[dict[str, Any]]) -> None:
    del linhas[0]["cod_marca"]


def _coluna_extra(linhas: list[dict[str, Any]]) -> None:
    linhas[0]["coluna_nova"] = 1


def _marca_como_texto(linhas: list[dict[str, Any]]) -> None:
    linhas[0]["cod_marca"] = "10"


def _marca_booleana(linhas: list[dict[str, Any]]) -> None:
    linhas[0]["cod_marca"] = True


def _marca_decimal(linhas: list[dict[str, Any]]) -> None:
    linhas[0]["cod_marca"] = 10.0


def _matricula_nula(linhas: list[dict[str, Any]]) -> None:
    linhas[0]["matricula"] = None


@pytest.mark.parametrize(
    ("estragar", "trecho"),
    [
        (_sem_coluna, "falta a coluna cod_marca"),
        (_coluna_extra, "colunas fora do schema"),
        (_marca_como_texto, "esperado inteiro"),
        (_marca_booleana, "esperado inteiro"),
        (_marca_decimal, "esperado inteiro"),
        (_matricula_nula, "esperado texto"),
    ],
)
def test_linha_do_rh_fora_do_schema_falha_alto(
    tmp_path: Path, estragar: Callable[[list[dict[str, Any]]], None], trecho: str
) -> None:
    linhas: list[dict[str, Any]] = [linha_rh()]
    estragar(linhas)
    raiz = dataset_de_um_funcionario(tmp_path, rh=linhas)

    with pytest.raises(CargaError, match=trecho):
        carregar(["2025-08"], raiz=raiz)


def test_mensagem_de_tipo_errado_nao_carrega_o_valor(tmp_path: Path) -> None:
    linha = linha_rh() | {"cod_marca": "SEGREDO-123"}
    raiz = dataset_de_um_funcionario(tmp_path, rh=[linha])

    with pytest.raises(CargaError) as erro:
        carregar(["2025-08"], raiz=raiz)

    assert "SEGREDO-123" not in str(erro.value)
    assert "linha 1" in str(erro.value)


def test_valor_nao_finito_no_json_falha_alto(tmp_path: Path) -> None:
    raiz = dataset_de_um_funcionario(tmp_path)
    (raiz / "vendas.jsonl").write_text(
        '{"competencia": "2025-08", "vlr_venda": NaN}\n', encoding="utf-8"
    )

    with pytest.raises(CargaError, match="não finito"):
        carregar(["2025-08"], raiz=raiz)


def test_matricula_repetida_no_rh_da_competencia_e_recusada(tmp_path: Path) -> None:
    raiz = dataset_de_um_funcionario(tmp_path, rh=[linha_rh(), linha_rh()])

    with pytest.raises(BaseInconsistenteError, match="repetida"):
        carregar(["2025-08"], raiz=raiz)


@pytest.mark.parametrize(
    ("baseline", "trecho"),
    [
        (linha_baseline(marcas=(20,)), "cod_marca do baseline"),
        (linha_baseline(cod_loja=99), "cod_loja do baseline"),
        (linha_baseline(cargo=300), "cod_cargo do baseline"),
        (linha_baseline(marcas=()), "chaves_comissao ausente ou vazia"),
        (linha_baseline(marcas=(10, 20)), "marca não é única"),
        (linha_baseline("MATRIC-9"), "não existe no rh"),
        (linha_baseline(competencia="2025-09"), "competência diferente"),
    ],
)
def test_baseline_que_diverge_do_rh_falha_alto(
    tmp_path: Path, baseline: dict[str, object], trecho: str
) -> None:
    raiz = dataset_de_um_funcionario(tmp_path, baselines={"2025-08": [baseline]})

    with pytest.raises(BaseInconsistenteError, match=trecho):
        carregar(["2025-08"], raiz=raiz)


def test_matricula_repetida_no_baseline_e_recusada(tmp_path: Path) -> None:
    raiz = dataset_de_um_funcionario(
        tmp_path, baselines={"2025-08": [linha_baseline(), linha_baseline()]}
    )

    with pytest.raises(BaseInconsistenteError, match="repetida"):
        carregar(["2025-08"], raiz=raiz)


@pytest.mark.parametrize(
    ("editar", "trecho"),
    [
        (lambda m: m["baselines"]["2025-08"].update(matriculas=2), "o manifesto registra 2"),
        (lambda m: m["baselines"]["2025-08"].update(total=99.99), "o manifesto registra 99.99"),
        (lambda m: m["baselines"].pop("2025-08"), "não tem o baseline de 2025-08"),
    ],
)
def test_baseline_que_nao_bate_com_o_manifesto_falha_alto(
    tmp_path: Path, editar: Callable[[dict[str, Any]], None], trecho: str
) -> None:
    raiz = dataset_de_um_funcionario(tmp_path, editar_manifesto=editar)

    with pytest.raises(BaseInconsistenteError, match=trecho):
        carregar(["2025-08"], raiz=raiz)


def test_dataset_minimo_valido_carrega(tmp_path: Path) -> None:
    """Controle: sem ele, os testes de erro acima poderiam falhar por outro motivo."""
    raiz = dataset_de_um_funcionario(tmp_path)

    entrada = carregar(["2025-08"], raiz=raiz)

    assert entrada.registros_base == (
        {
            "matricula": "MATRIC-1",
            "cod_loja": 1,
            "cod_marca": 10,
            "cod_cargo": 100,
            "competencia": "2025-08",
            "comissao": 100.0,
        },
    )
