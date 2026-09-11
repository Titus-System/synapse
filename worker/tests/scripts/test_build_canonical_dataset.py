from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]

from scripts.build_canonical_dataset import (
    COMISSOES_FIELD_ORDER,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SOURCE_ROOT,
    RH_FIELD_ORDER,
    VENDAS_FIELD_ORDER,
    CompetenciaSource,
    build_dataset,
    build_rh_rows,
    empty_report,
    manifest,
)

COMPETENCIA_PATTERN = re.compile(r"^2025-(07|08|09|10|11|12)$")
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ARTIFACT_NAMES = (
    "rh.jsonl",
    "vendas.jsonl",
    "comissoes.jsonl",
    "schema.json",
    "normalization_report.json",
)


@pytest.fixture(scope="session")
def canonical_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    generated_dir = tmp_path_factory.mktemp("canonical")
    build_dataset(source_root=DEFAULT_SOURCE_ROOT, output_dir=generated_dir)

    return generated_dir


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="session")
def rh_rows(canonical_dir: Path) -> list[dict[str, Any]]:
    return read_jsonl(canonical_dir / "rh.jsonl")


@pytest.fixture(scope="session")
def vendas_rows(canonical_dir: Path) -> list[dict[str, Any]]:
    return read_jsonl(canonical_dir / "vendas.jsonl")


@pytest.fixture(scope="session")
def comissoes_rows(canonical_dir: Path) -> list[dict[str, Any]]:
    return read_jsonl(canonical_dir / "comissoes.jsonl")


def test_all_five_artifacts_exist(canonical_dir: Path) -> None:
    assert {path.name for path in canonical_dir.iterdir()} == set(ARTIFACT_NAMES)


def test_versioned_artifacts_match_generated_artifacts(
    tmp_path: Path,
) -> None:
    generated_dir = tmp_path / "generated"

    build_dataset(source_root=DEFAULT_SOURCE_ROOT, output_dir=generated_dir)

    for artifact_name in ARTIFACT_NAMES:
        assert (generated_dir / artifact_name).read_bytes() == (
            DEFAULT_OUTPUT_DIR / artifact_name
        ).read_bytes()


@pytest.mark.parametrize("fixture_name", ["rh_rows", "vendas_rows", "comissoes_rows"])
def test_every_row_has_valid_competencia(request: pytest.FixtureRequest, fixture_name: str) -> None:
    rows = request.getfixturevalue(fixture_name)

    assert all(COMPETENCIA_PATTERN.match(row["competencia"]) for row in rows)


def test_canonical_dates_are_not_excel_serials(
    rh_rows: list[dict[str, Any]],
    vendas_rows: list[dict[str, Any]],
) -> None:
    date_values: list[str] = []
    date_values.extend(row["data_ref"] for row in rh_rows)
    date_values.extend(row["data_admiss"] for row in rh_rows)
    date_values.extend(row["data_demiss"] for row in rh_rows if row["data_demiss"] is not None)
    date_values.extend(row["data_ref"] for row in vendas_rows)
    date_values.extend(row["data_venda"] for row in vendas_rows if row["data_venda"] is not None)

    assert all(isinstance(value, str) for value in date_values)
    assert not any(isinstance(value, int | float) for value in date_values)


def test_canonical_dates_use_iso_format(
    rh_rows: list[dict[str, Any]],
    vendas_rows: list[dict[str, Any]],
) -> None:
    date_values: list[str] = []
    date_values.extend(row["data_ref"] for row in rh_rows)
    date_values.extend(row["data_admiss"] for row in rh_rows)
    date_values.extend(row["data_demiss"] for row in rh_rows if row["data_demiss"] is not None)
    date_values.extend(row["data_ref"] for row in vendas_rows)
    date_values.extend(row["data_venda"] for row in vendas_rows if row["data_venda"] is not None)

    assert all(ISO_DATE_PATTERN.match(value) for value in date_values)


def test_matricula_is_string_and_preserves_matric_prefix(
    rh_rows: list[dict[str, Any]],
    vendas_rows: list[dict[str, Any]],
) -> None:
    matriculas = [row["matricula"] for row in rh_rows + vendas_rows]

    assert all(isinstance(matricula, str) for matricula in matriculas)
    assert all(matricula.startswith("MATRIC-") for matricula in matriculas)


def test_percentual_comissao_remains_fraction(comissoes_rows: list[dict[str, Any]]) -> None:
    percentuais = [row["percentual_comissao"] for row in comissoes_rows]

    assert max(percentuais) < 1
    assert Decimal(str(percentuais[0])) == Decimal("0.025")


def test_novembro_keeps_the_same_vendas_row_count(vendas_rows: list[dict[str, Any]]) -> None:
    source_count = source_vendas_row_count("2025-11")

    canonical_count = sum(1 for row in vendas_rows if row["competencia"] == "2025-11")

    assert canonical_count == source_count


def test_novembro_keeps_the_same_vendas_total(vendas_rows: list[dict[str, Any]]) -> None:
    source_total = source_vendas_total("2025-11")
    canonical_total = sum(
        (
            Decimal(str(row["vlr_venda"]))
            for row in vendas_rows
            if row["competencia"] == "2025-11"
        ),
        Decimal("0"),
    )

    assert canonical_total == source_total


def test_vendas_from_november_24_to_28_have_data_venda(
    vendas_rows: list[dict[str, Any]],
) -> None:
    rows = [
        row
        for row in vendas_rows
        if row["competencia"] == "2025-11" and row["data_ref"] in november_real_sale_dates()
    ]

    assert len(rows) == 721
    assert all(row["data_venda"] == row["data_ref"] for row in rows)


def test_vendas_from_november_first_have_null_data_venda(
    vendas_rows: list[dict[str, Any]],
) -> None:
    rows = [
        row
        for row in vendas_rows
        if row["competencia"] == "2025-11" and row["data_ref"] == "2025-11-01"
    ]

    assert len(rows) == 4279
    assert all(row["data_venda"] is None for row in rows)


def test_other_five_competencias_do_not_have_unexpected_data_venda(
    vendas_rows: list[dict[str, Any]],
) -> None:
    rows = [row for row in vendas_rows if row["competencia"] != "2025-11"]

    assert all(row["data_venda"] is None for row in rows)


def test_cargo_150_keeps_both_manager_descriptions(
    rh_rows: list[dict[str, Any]],
    comissoes_rows: list[dict[str, Any]],
) -> None:
    expected = {"GERENTE DE LOJA", "GERENTE QUIOSQUE"}
    rh_descriptions = {row["descr_cargo"] for row in rh_rows if row["cod_cargo"] == 150}
    comissao_descriptions = {
        row["descr_cargo"] for row in comissoes_rows if row["cod_cargo"] == 150
    }

    assert expected <= rh_descriptions
    assert expected <= comissao_descriptions


def test_vendas_reais_column_is_not_in_canonical_rh(rh_rows: list[dict[str, Any]]) -> None:
    assert all("VENDAS R$" not in row for row in rh_rows)


def test_setembro_matric_246_duplicate_is_handled(
    canonical_dir: Path,
    rh_rows: list[dict[str, Any]],
) -> None:
    rows = [
        row
        for row in rh_rows
        if row["competencia"] == "2025-09" and row["matricula"] == "MATRIC-246"
    ]
    report = json.loads((canonical_dir / "normalization_report.json").read_text(encoding="utf-8"))

    assert len(rows) == 1
    assert len(report["discarded_rows"]) == 1
    discarded = report["discarded_rows"][0]
    assert discarded["dataset"] == "rh"
    assert discarded["competencia"] == "2025-09"
    assert discarded["source_file"] == "dataset_domrock/BASE RH/BASE RH_SET25.xlsx"
    assert discarded["source_sheet"] == "BASE HC"
    assert discarded["matricula"] == "MATRIC-246"
    assert discarded["reason"] == "duplicate_integral_rh_row_for_matric_246"
    assert discarded["source_row"] > discarded["kept_source_row"]


@pytest.mark.parametrize("cargo_code", [100, 150, 200, 300])
def test_data_demiss_rejects_known_cargo_codes_before_date_conversion(
    tmp_path: Path,
    cargo_code: int,
) -> None:
    source_file = tmp_path / f"rh_data_demiss_{cargo_code}.xlsx"
    write_rh_workbook_with_data_demiss(source_file, cargo_code)
    source = CompetenciaSource(
        competencia="2025-07",
        rh_file=source_file,
        rh_sheet="BASE HC",
        vendas_file=tmp_path / "unused.xlsx",
        vendas_sheet="VENDAS",
    )

    with pytest.raises(ValueError) as exc_info:
        build_rh_rows(source, empty_report())

    message = str(exc_info.value)
    assert "Possible Data_Demiss/Cod_Cargo misalignment" in message
    assert "file=" in message
    assert source_file.name in message
    assert "competencia=2025-07" in message
    assert "row=2" in message
    assert f"Data_Demiss={cargo_code}" in message


def test_vendas_duplicates_are_not_removed(vendas_rows: list[dict[str, Any]]) -> None:
    counts = Counter(
        tuple(row[field] for field in VENDAS_FIELD_ORDER if field != "data_venda")
        for row in vendas_rows
    )

    assert any(count > 1 for count in counts.values())
    source_count = sum(
        source_vendas_row_count(source.competencia) for source in manifest(DEFAULT_SOURCE_ROOT)
    )

    assert len(vendas_rows) == source_count


def test_schema_matches_physical_jsonl_fields(
    canonical_dir: Path,
    rh_rows: list[dict[str, Any]],
    vendas_rows: list[dict[str, Any]],
    comissoes_rows: list[dict[str, Any]],
) -> None:
    schema = json.loads((canonical_dir / "schema.json").read_text(encoding="utf-8"))

    assert [field["name"] for field in schema["tables"]["rh"]["fields"]] == list(rh_rows[0])
    assert [field["name"] for field in schema["tables"]["vendas"]["fields"]] == list(vendas_rows[0])
    assert [field["name"] for field in schema["tables"]["comissoes"]["fields"]] == list(
        comissoes_rows[0]
    )
    assert list(rh_rows[0]) == list(RH_FIELD_ORDER)
    assert list(vendas_rows[0]) == list(VENDAS_FIELD_ORDER)
    assert list(comissoes_rows[0]) == list(COMISSOES_FIELD_ORDER)


def test_comissao_is_expanded_to_180_records(comissoes_rows: list[dict[str, Any]]) -> None:
    assert len(comissoes_rows) == 180


def test_two_independent_runs_generate_identical_artifacts(tmp_path: Path) -> None:
    first_dir = tmp_path / "run_a"
    second_dir = tmp_path / "run_b"

    first = build_dataset(source_root=DEFAULT_SOURCE_ROOT, output_dir=first_dir)
    second = build_dataset(source_root=DEFAULT_SOURCE_ROOT, output_dir=second_dir)

    assert first.hashes == second.hashes
    for artifact_name in ARTIFACT_NAMES:
        assert (first_dir / artifact_name).read_bytes() == (
            second_dir / artifact_name
        ).read_bytes()


def test_report_includes_data_venda_zero_counts_for_all_competencias(
    canonical_dir: Path,
) -> None:
    report = json.loads((canonical_dir / "normalization_report.json").read_text(encoding="utf-8"))

    assert report["checks"]["vendas"]["data_venda_rows_by_competencia"] == {
        "2025-07": 0,
        "2025-08": 0,
        "2025-09": 0,
        "2025-10": 0,
        "2025-11": 721,
        "2025-12": 0,
    }


def source_vendas_row_count(competencia: str) -> int:
    source = next(item for item in manifest(DEFAULT_SOURCE_ROOT) if item.competencia == competencia)
    return len(read_source_rows(source.vendas_file, source.vendas_sheet))


def source_vendas_total(competencia: str) -> Decimal:
    source = next(item for item in manifest(DEFAULT_SOURCE_ROOT) if item.competencia == competencia)
    return sum(
        (
            Decimal(str(row["Vlr _Venda"]))
            for row in read_source_rows(source.vendas_file, source.vendas_sheet)
        ),
        Decimal("0"),
    )


def read_source_rows(path: Path, sheet_name: str) -> list[dict[str, Any]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet_name]
        rows = worksheet.iter_rows(values_only=True)
        headers = [str(value).strip() for value in next(rows)]
        return [
            dict(zip(headers, row, strict=True))
            for row in rows
            if not all(value is None for value in row)
        ]
    finally:
        workbook.close()


def write_rh_workbook_with_data_demiss(path: Path, data_demiss: int) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "BASE HC"
    worksheet.append(list(RH_SOURCE_HEADERS))
    worksheet.append(
        [
            date(2025, 7, 1),
            1,
            "MARCA",
            101,
            "LOJA",
            "MATRIC-001",
            date(2025, 1, 1),
            data_demiss,
            100,
            "VENDEDOR",
        ]
    )
    workbook.save(path)


RH_SOURCE_HEADERS = (
    "Data_Ref",
    "Cod_Marca",
    "Descri_Marca",
    "Cod_Loja",
    "Descr_Loja",
    "Matricula",
    "Data_Admiss",
    "Data_Demiss",
    "Cod_Cargo",
    "Descri_Cargo",
)


def november_real_sale_dates() -> set[str]:
    return {
        "2025-11-24",
        "2025-11-25",
        "2025-11-26",
        "2025-11-27",
        "2025-11-28",
    }
