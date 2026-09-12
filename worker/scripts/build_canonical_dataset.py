from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from openpyxl import load_workbook  # type: ignore[import-untyped]
from openpyxl.utils.datetime import from_excel  # type: ignore[import-untyped]

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | Sequence[JsonValue] | Mapping[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type CellValue = str | int | float | datetime | date | None

WORKER_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WORKER_ROOT.parent
DEFAULT_SOURCE_ROOT = PROJECT_ROOT / "dataset_domrock"
DEFAULT_OUTPUT_DIR = WORKER_ROOT / "sandbox" / "data" / "domrock"

RH_FIELD_ORDER = (
    "competencia",
    "data_ref",
    "cod_marca",
    "descr_marca",
    "cod_loja",
    "descr_loja",
    "matricula",
    "data_admiss",
    "data_demiss",
    "cod_cargo",
    "descr_cargo",
)
VENDAS_FIELD_ORDER = (
    "competencia",
    "data_ref",
    "data_venda",
    "cod_marca",
    "descr_marca",
    "cod_loja",
    "descr_loja",
    "matricula",
    "vlr_venda",
)
COMISSOES_FIELD_ORDER = (
    "competencia",
    "cod_marca",
    "descr_marca",
    "cod_cargo",
    "descr_cargo",
    "percentual_comissao",
)

RH_COLUMN_MAP = {
    "Data_Ref": "data_ref",
    "Cod_Marca": "cod_marca",
    "Descri_Marca": "descr_marca",
    "Cod_Loja": "cod_loja",
    "Descr_Loja": "descr_loja",
    "Matricula": "matricula",
    "Data_Admiss": "data_admiss",
    "Data_Demiss": "data_demiss",
    "Cod_Cargo": "cod_cargo",
    "Descri_Cargo": "descr_cargo",
}
VENDAS_COLUMN_MAP = {
    "Date_Ref": "data_ref",
    "Cod_Marca": "cod_marca",
    "Descr_Marca": "descr_marca",
    "Cod_Loja": "cod_loja",
    "Descr_Loja": "descr_loja",
    "Matricula": "matricula",
    "Vlr _Venda": "vlr_venda",
}
COMISSOES_COLUMN_MAP = {
    "Cod_Marca": "cod_marca",
    "Descr_Marca": "descr_marca",
    "Cod_Cargo": "cod_cargo",
    "Descri_Cargo": "descr_cargo",
    "%_Comiss": "percentual_comissao",
}
KNOWN_CARGO_CODES = frozenset({100, 150, 200, 300})


@dataclass(frozen=True)
class CompetenciaSource:
    competencia: str
    rh_file: Path
    rh_sheet: str
    vendas_file: Path
    vendas_sheet: str


@dataclass(frozen=True)
class SourceRow:
    row_number: int
    values: dict[str, CellValue]


@dataclass(frozen=True)
class SourceTable:
    headers: tuple[str, ...]
    rows: tuple[SourceRow, ...]


@dataclass(frozen=True)
class CanonicalRow:
    source_file: Path
    source_sheet: str
    source_row: int
    record: JsonObject


@dataclass(frozen=True)
class BuildResult:
    output_dir: Path
    artifacts: tuple[Path, ...]
    hashes: dict[str, str]


def manifest(source_root: Path) -> tuple[CompetenciaSource, ...]:
    return (
        CompetenciaSource(
            competencia="2025-07",
            rh_file=source_root / "BASE RH" / "BASE RH_JUL25.xlsx",
            rh_sheet="BASE HC",
            vendas_file=source_root / "BASE_VENDAS" / "BASE_VENDAS_JUL25.xlsx",
            vendas_sheet="VENDAS",
        ),
        CompetenciaSource(
            competencia="2025-08",
            rh_file=source_root / "BASE RH" / "BASE RH_AGO25.xlsx",
            rh_sheet="BASE HC",
            vendas_file=source_root / "BASE_VENDAS" / "BASE_VENDAS_AGO25.xlsx",
            vendas_sheet="VENDAS",
        ),
        CompetenciaSource(
            competencia="2025-09",
            rh_file=source_root / "BASE RH" / "BASE RH_SET25.xlsx",
            rh_sheet="BASE HC",
            vendas_file=source_root / "BASE_VENDAS" / "BASE_VENDAS_SET25.xlsx",
            vendas_sheet="VENDAS",
        ),
        CompetenciaSource(
            competencia="2025-10",
            rh_file=source_root / "BASE RH" / "BASE RH_OUT25.xlsx",
            rh_sheet="BASE HC",
            vendas_file=source_root / "BASE_VENDAS" / "BASE_VENDAS_OUT25.xlsx",
            vendas_sheet="VENDAS",
        ),
        CompetenciaSource(
            competencia="2025-11",
            rh_file=source_root / "BASE RH" / "BASE RH_NOV25.xlsx",
            rh_sheet="BASE HC",
            vendas_file=source_root / "BASE_VENDAS" / "BASE_VENDAS_NOV25.xlsx",
            vendas_sheet="VENDAS",
        ),
        CompetenciaSource(
            competencia="2025-12",
            rh_file=source_root / "BASE RH" / "BASE RH_DEZ25.xlsx",
            rh_sheet="BASE HC",
            vendas_file=source_root / "BASE_VENDAS" / "BASE_VENDAS_DEZ25.xlsx",
            vendas_sheet="VENDAS",
        ),
    )


def build_dataset(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> BuildResult:
    report = empty_report()
    competencia_sources = manifest(source_root)
    rh_rows: list[CanonicalRow] = []
    vendas_rows: list[CanonicalRow] = []
    comissoes_rows: list[CanonicalRow] = []

    for source in competencia_sources:
        rh_rows.extend(build_rh_rows(source, report))
        vendas_rows.extend(build_vendas_rows(source, report))

    register_missing_rh_warnings(rh_rows, vendas_rows, report)
    comissoes_rows.extend(
        build_comissoes_rows(
            source_root / "BASE_COMMISS_FINAL.xlsx",
            "Commission",
            tuple(source.competencia for source in competencia_sources),
            report,
        )
    )

    report["checks"] = build_checks(rh_rows, vendas_rows, comissoes_rows, report)

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = (
        output_dir / "rh.jsonl",
        output_dir / "vendas.jsonl",
        output_dir / "comissoes.jsonl",
        output_dir / "schema.json",
        output_dir / "normalization_report.json",
    )
    write_jsonl(artifacts[0], (row.record for row in rh_rows))
    write_jsonl(artifacts[1], (row.record for row in vendas_rows))
    write_jsonl(artifacts[2], (row.record for row in comissoes_rows))
    write_json(artifacts[3], build_schema())
    write_json(artifacts[4], report)

    return BuildResult(
        output_dir=output_dir,
        artifacts=artifacts,
        hashes={path.name: sha256_file(path) for path in artifacts},
    )


def empty_report() -> JsonObject:
    return {
        "source_validations": {
            "rh": {},
            "vendas": {},
            "comissoes": {},
        },
        "normalizations_applied": [],
        "discarded_rows": [],
        "discarded_columns": [],
        "warnings": [],
        "checks": {},
    }


def build_rh_rows(source: CompetenciaSource, report: JsonObject) -> list[CanonicalRow]:
    table = read_sheet(source.rh_file, source.rh_sheet)
    validate_columns(
        headers=table.headers,
        expected=tuple(RH_COLUMN_MAP),
        allowed_extra=("VENDAS R$",) if source.competencia == "2025-09" else (),
        source_file=source.rh_file,
    )
    validate_data_demiss_alignment(source, table)
    if "VENDAS R$" in table.headers:
        discarded_columns(report).append(
            {
                "dataset": "rh",
                "competencia": source.competencia,
                "source_file": relative_source(source.rh_file),
                "source_sheet": source.rh_sheet,
                "source_column": "VENDAS R$",
                "reason": "not_in_canonical_rh_schema",
            }
        )

    rows = [
        CanonicalRow(
            source_file=source.rh_file,
            source_sheet=source.rh_sheet,
            source_row=row.row_number,
            record={
                "competencia": source.competencia,
                "data_ref": required_date(row.values["Data_Ref"], "Data_Ref"),
                "cod_marca": required_int(row.values["Cod_Marca"], "Cod_Marca"),
                "descr_marca": required_string(row.values["Descri_Marca"], "Descri_Marca"),
                "cod_loja": required_int(row.values["Cod_Loja"], "Cod_Loja"),
                "descr_loja": required_string(row.values["Descr_Loja"], "Descr_Loja"),
                "matricula": required_string(row.values["Matricula"], "Matricula"),
                "data_admiss": required_date(row.values["Data_Admiss"], "Data_Admiss"),
                "data_demiss": optional_date(row.values["Data_Demiss"], "Data_Demiss"),
                "cod_cargo": required_int(row.values["Cod_Cargo"], "Cod_Cargo"),
                "descr_cargo": required_string(row.values["Descri_Cargo"], "Descri_Cargo"),
            },
        )
        for row in table.rows
    ]
    rows = discard_known_rh_duplicate(source, rows, report)
    register_rh_validation(source, table, rows, report)
    register_date_normalizations(
        report,
        dataset="rh",
        competencia=source.competencia,
        fields=("Data_Ref", "Data_Admiss", "Data_Demiss"),
    )
    return rows


def build_vendas_rows(source: CompetenciaSource, report: JsonObject) -> list[CanonicalRow]:
    table = read_sheet(source.vendas_file, source.vendas_sheet)
    validate_columns(
        headers=table.headers,
        expected=tuple(VENDAS_COLUMN_MAP),
        allowed_extra=(),
        source_file=source.vendas_file,
    )
    rows = [
        build_venda_row(source, row)
        for row in table.rows
    ]
    register_vendas_validation(source, table, rows, report)
    register_date_normalizations(
        report,
        dataset="vendas",
        competencia=source.competencia,
        fields=("Date_Ref",),
    )
    return rows


def build_venda_row(source: CompetenciaSource, row: SourceRow) -> CanonicalRow:
    data_ref = required_date(row.values["Date_Ref"], "Date_Ref")
    return CanonicalRow(
        source_file=source.vendas_file,
        source_sheet=source.vendas_sheet,
        source_row=row.row_number,
        record={
            "competencia": source.competencia,
            "data_ref": data_ref,
            "data_venda": data_ref if is_real_sale_date(source.competencia, data_ref) else None,
            "cod_marca": required_int(row.values["Cod_Marca"], "Cod_Marca"),
            "descr_marca": required_string(row.values["Descr_Marca"], "Descr_Marca"),
            "cod_loja": required_int(row.values["Cod_Loja"], "Cod_Loja"),
            "descr_loja": required_string(row.values["Descr_Loja"], "Descr_Loja"),
            "matricula": required_string(row.values["Matricula"], "Matricula"),
            "vlr_venda": required_number(row.values["Vlr _Venda"], "Vlr _Venda"),
        },
    )


def build_comissoes_rows(
    source_file: Path,
    sheet_name: str,
    competencias: tuple[str, ...],
    report: JsonObject,
) -> list[CanonicalRow]:
    table = read_sheet(source_file, sheet_name)
    validate_columns(
        headers=table.headers,
        expected=tuple(COMISSOES_COLUMN_MAP),
        allowed_extra=(),
        source_file=source_file,
    )
    rows: list[CanonicalRow] = []
    for competencia in competencias:
        for row in table.rows:
            rows.append(
                CanonicalRow(
                    source_file=source_file,
                    source_sheet=sheet_name,
                    source_row=row.row_number,
                    record={
                        "competencia": competencia,
                        "cod_marca": required_int(row.values["Cod_Marca"], "Cod_Marca"),
                        "descr_marca": required_string(row.values["Descr_Marca"], "Descr_Marca"),
                        "cod_cargo": required_int(row.values["Cod_Cargo"], "Cod_Cargo"),
                        "descr_cargo": required_string(row.values["Descri_Cargo"], "Descri_Cargo"),
                        "percentual_comissao": required_number(
                            row.values["%_Comiss"],
                            "%_Comiss",
                        ),
                    },
                )
            )

    source_validations(report)["comissoes"] = {
        "source_file": relative_source(source_file),
        "source_sheet": sheet_name,
        "source_row_count": len(table.rows),
        "canonical_row_count": len(rows),
        "expanded_competencias": list(competencias),
    }
    return rows


def read_sheet(path: Path, sheet_name: str) -> SourceTable:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet_name]
        rows = worksheet.iter_rows(values_only=True)
        header_values = next(rows)
        headers = tuple(normalize_header(value) for value in header_values)
        if "" in headers:
            raise ValueError(f"{path} has an empty header")
        if len(set(headers)) != len(headers):
            raise ValueError(f"{path} has duplicate headers after trimming")

        source_rows: list[SourceRow] = []
        for row_number, row_values in enumerate(rows, start=2):
            values = tuple(cast(CellValue, value) for value in row_values[: len(headers)])
            if all(value is None for value in values):
                continue
            source_rows.append(SourceRow(row_number, dict(zip(headers, values, strict=True))))
        return SourceTable(headers, tuple(source_rows))
    finally:
        workbook.close()


def validate_columns(
    *,
    headers: tuple[str, ...],
    expected: tuple[str, ...],
    allowed_extra: tuple[str, ...],
    source_file: Path,
) -> None:
    missing = sorted(set(expected) - set(headers))
    extra = sorted(set(headers) - set(expected) - set(allowed_extra))
    if missing or extra:
        raise ValueError(
            f"{source_file} has invalid columns: missing={missing}, extra={extra}"
        )


def validate_data_demiss_alignment(source: CompetenciaSource, table: SourceTable) -> None:
    for row in table.rows:
        data_demiss = row.values["Data_Demiss"]
        cargo_code = known_cargo_code_value(data_demiss)
        if cargo_code is not None:
            raise ValueError(
                "Possible Data_Demiss/Cod_Cargo misalignment: "
                f"file={source_label(source.rh_file)}, "
                f"competencia={source.competencia}, "
                f"row={row.row_number}, "
                f"Data_Demiss={cargo_code}"
            )


def known_cargo_code_value(value: CellValue) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int) and value in KNOWN_CARGO_CODES:
        return value
    if isinstance(value, float) and value.is_integer() and int(value) in KNOWN_CARGO_CODES:
        return int(value)
    return None


def discard_known_rh_duplicate(
    source: CompetenciaSource,
    rows: list[CanonicalRow],
    report: JsonObject,
) -> list[CanonicalRow]:
    if source.competencia != "2025-09":
        return rows

    matric_246_rows = [row for row in rows if row.record["matricula"] == "MATRIC-246"]
    if len(matric_246_rows) != 2 or matric_246_rows[0].record != matric_246_rows[1].record:
        raise ValueError("Expected exactly one integral RH duplicate for MATRIC-246 in 2025-09")

    kept, discarded = matric_246_rows
    discarded_rows(report).append(
        {
            "dataset": "rh",
            "competencia": source.competencia,
            "source_file": relative_source(discarded.source_file),
            "source_sheet": discarded.source_sheet,
            "source_row": discarded.source_row,
            "matricula": "MATRIC-246",
            "reason": "duplicate_integral_rh_row_for_matric_246",
            "kept_source_row": kept.source_row,
        }
    )

    removed = False
    result: list[CanonicalRow] = []
    for row in rows:
        if row is discarded and not removed:
            removed = True
            continue
        result.append(row)
    return result


def register_rh_validation(
    source: CompetenciaSource,
    table: SourceTable,
    rows: list[CanonicalRow],
    report: JsonObject,
) -> None:
    invalid_data_demiss_rows = [
        row.row_number
        for row in table.rows
        if row.values["Data_Demiss"] is not None
        and optional_date(row.values["Data_Demiss"], "Data_Demiss") is None
    ]
    invalid_cod_cargo_rows = [
        row.source_row
        for row in rows
        if not isinstance(row.record["cod_cargo"], int)
    ]
    source_validations(report)["rh"][source.competencia] = {
        "source_file": relative_source(source.rh_file),
        "source_sheet": source.rh_sheet,
        "source_row_count": len(table.rows),
        "canonical_row_count": len(rows),
        "headers_after_trim": list(table.headers),
        "data_demiss_cod_cargo_alignment": {
            "checked": True,
            "result": "ok",
            "known_cargo_codes_checked": sorted(KNOWN_CARGO_CODES),
            "known_cargo_code_values_in_data_demiss": [],
            "invalid_data_demiss_rows": invalid_data_demiss_rows,
            "invalid_cod_cargo_rows": invalid_cod_cargo_rows,
            "message": "Data_Demiss validated as date/null and Cod_Cargo validated as integer.",
        },
    }


def register_vendas_validation(
    source: CompetenciaSource,
    table: SourceTable,
    rows: list[CanonicalRow],
    report: JsonObject,
) -> None:
    date_ref_counts: dict[str, int] = defaultdict(int)
    non_month_reference_dates: dict[str, int] = defaultdict(int)
    for row in rows:
        data_ref = cast(str, row.record["data_ref"])
        date_ref_counts[data_ref] += 1
        if not data_ref.endswith("-01"):
            non_month_reference_dates[data_ref] += 1

    source_validations(report)["vendas"][source.competencia] = {
        "source_file": relative_source(source.vendas_file),
        "source_sheet": source.vendas_sheet,
        "source_row_count": len(table.rows),
        "canonical_row_count": len(rows),
        "date_ref_check": {
            "checked": True,
            "non_day_one_count": sum(non_month_reference_dates.values()),
            "non_day_one_dates": sorted_dict(non_month_reference_dates),
            "all_date_ref_counts": sorted_dict(date_ref_counts),
        },
        "source_total_vlr_venda": decimal_text(sum_source_vlr_venda(table)),
        "canonical_total_vlr_venda": decimal_text(sum_record_number(rows, "vlr_venda")),
    }


def register_missing_rh_warnings(
    rh_rows: list[CanonicalRow],
    vendas_rows: list[CanonicalRow],
    report: JsonObject,
) -> None:
    rh_by_competencia: dict[str, set[str]] = defaultdict(set)
    vendas_by_competencia: dict[str, set[str]] = defaultdict(set)
    for row in rh_rows:
        rh_by_competencia[cast(str, row.record["competencia"])].add(
            cast(str, row.record["matricula"])
        )
    for row in vendas_rows:
        vendas_by_competencia[cast(str, row.record["competencia"])].add(
            cast(str, row.record["matricula"])
        )

    for competencia in sorted(vendas_by_competencia):
        missing = sorted(vendas_by_competencia[competencia] - rh_by_competencia[competencia])
        if missing:
            warnings(report).append(
                {
                    "dataset": "vendas",
                    "competencia": competencia,
                    "warning": "matriculas_presentes_em_vendas_ausentes_no_rh",
                    "count": len(missing),
                    "matriculas": missing,
                    "action": "preserved",
                }
            )


def build_checks(
    rh_rows: list[CanonicalRow],
    vendas_rows: list[CanonicalRow],
    comissoes_rows: list[CanonicalRow],
    report: JsonObject,
) -> JsonObject:
    vendas_counts: dict[str, int] = defaultdict(int)
    vendas_data_venda_counts: dict[str, int] = defaultdict(int)
    competencias = sorted(
        {
            cast(str, row.record["competencia"])
            for row in [*rh_rows, *vendas_rows, *comissoes_rows]
        }
    )
    for row in vendas_rows:
        competencia = cast(str, row.record["competencia"])
        vendas_counts[competencia] += 1
        if row.record["data_venda"] is not None:
            vendas_data_venda_counts[competencia] += 1

    return {
        "determinism": {
            "encoding": "utf-8",
            "line_endings": "LF",
            "field_order": "fixed",
            "record_order": "manifest_order_then_source_row_order",
            "timestamps": "not_included",
            "uuids": "not_included",
        },
        "rh": {
            "total_rows": len(rh_rows),
            "setembro_matric_246_duplicate": {
                "handled": True,
                "discarded_rows": [
                    item
                    for item in discarded_rows(report)
                    if item.get("reason") == "duplicate_integral_rh_row_for_matric_246"
                ],
            },
            "discarded_columns": discarded_columns(report),
        },
        "vendas": {
            "rows_by_competencia": counts_for_competencias(vendas_counts, competencias),
            "data_venda_rows_by_competencia": counts_for_competencias(
                vendas_data_venda_counts,
                competencias,
            ),
            "duplicates_policy": "preserved",
        },
        "comissoes": {
            "source_rows": 30,
            "competencias": 6,
            "expected_rows": 180,
            "actual_rows": len(comissoes_rows),
        },
    }


def register_date_normalizations(
    report: JsonObject,
    *,
    dataset: str,
    competencia: str,
    fields: tuple[str, ...],
) -> None:
    normalizations_applied(report).append(
        {
            "dataset": dataset,
            "competencia": competencia,
            "fields": list(fields),
            "normalization": "date_cells_to_iso_yyyy_mm_dd",
        }
    )


def is_real_sale_date(competencia: str, data_ref: str) -> bool:
    return competencia == "2025-11" and data_ref in {
        "2025-11-24",
        "2025-11-25",
        "2025-11-26",
        "2025-11-27",
        "2025-11-28",
    }


def normalize_header(value: object) -> str:
    return "" if value is None else str(value).strip()


def required_string(value: CellValue, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required")
    return str(value)


def required_int(value: CellValue, field_name: str) -> int:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"{field_name} must be an integer, got {value!r}")


def required_number(value: CellValue, field_name: str) -> int | float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    raise ValueError(f"{field_name} must be numeric, got {value!r}")


def optional_date(value: CellValue, field_name: str) -> str | None:
    if value is None:
        return None
    return required_date(value, field_name)


def required_date(value: CellValue, field_name: str) -> str:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a date")
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int | float):
        return cast(datetime, from_excel(value)).date().isoformat()
    if isinstance(value, str):
        return date.fromisoformat(value).isoformat()
    raise ValueError(f"{field_name} must be a date, got {value!r}")


def sum_source_vlr_venda(table: SourceTable) -> Decimal:
    return sum(
        (Decimal(str(row.values["Vlr _Venda"])) for row in table.rows),
        Decimal("0"),
    )


def sum_record_number(rows: list[CanonicalRow], field_name: str) -> Decimal:
    return sum(
        (Decimal(str(row.record[field_name])) for row in rows),
        Decimal("0"),
    )


def decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def sorted_dict(values: dict[str, int]) -> JsonObject:
    return {key: values[key] for key in sorted(values)}


def counts_for_competencias(values: dict[str, int], competencias: Sequence[str]) -> JsonObject:
    return {competencia: values.get(competencia, 0) for competencia in competencias}


def relative_source(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def source_label(path: Path) -> str:
    try:
        return relative_source(path)
    except ValueError:
        return str(path)


def write_jsonl(path: Path, rows: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in cast(Any, rows):
            file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            file.write("\n")


def write_json(path: Path, data: JsonObject) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_validations(report: JsonObject) -> dict[str, JsonObject]:
    return cast(dict[str, JsonObject], report["source_validations"])


def normalizations_applied(report: JsonObject) -> list[JsonObject]:
    return cast(list[JsonObject], report["normalizations_applied"])


def discarded_rows(report: JsonObject) -> list[JsonObject]:
    return cast(list[JsonObject], report["discarded_rows"])


def discarded_columns(report: JsonObject) -> list[JsonObject]:
    return cast(list[JsonObject], report["discarded_columns"])


def warnings(report: JsonObject) -> list[JsonObject]:
    return cast(list[JsonObject], report["warnings"])


def build_schema() -> JsonObject:
    return {
        "version": 1,
        "format": "jsonl",
        "tables": {
            "rh": {
                "file": "rh.jsonl",
                "fields": [
                    field(
                        "competencia",
                        None,
                        "string",
                        False,
                        "YYYY-MM",
                        "Explicit source manifest competency.",
                    ),
                    field(
                        "data_ref",
                        "Data_Ref",
                        "string",
                        False,
                        "YYYY-MM-DD",
                        "Monthly reference date from RH source.",
                    ),
                    field("cod_marca", "Cod_Marca", "integer", False, None, "Brand code."),
                    field(
                        "descr_marca",
                        "Descri_Marca",
                        "string",
                        False,
                        None,
                        "Brand description.",
                    ),
                    field("cod_loja", "Cod_Loja", "integer", False, None, "Store code."),
                    field("descr_loja", "Descr_Loja", "string", False, None, "Store description."),
                    field(
                        "matricula",
                        "Matricula",
                        "string",
                        False,
                        None,
                        "Employee identifier preserved as text.",
                    ),
                    field(
                        "data_admiss",
                        "Data_Admiss",
                        "string",
                        False,
                        "YYYY-MM-DD",
                        "Admission date.",
                    ),
                    field(
                        "data_demiss",
                        "Data_Demiss",
                        "string",
                        True,
                        "YYYY-MM-DD",
                        "Termination date when present.",
                    ),
                    field("cod_cargo", "Cod_Cargo", "integer", False, None, "Role code."),
                    field(
                        "descr_cargo",
                        "Descri_Cargo",
                        "string",
                        False,
                        None,
                        "Role description.",
                    ),
                ],
            },
            "vendas": {
                "file": "vendas.jsonl",
                "fields": [
                    field(
                        "competencia",
                        None,
                        "string",
                        False,
                        "YYYY-MM",
                        "Compet\u00eancia expl\u00edcita do registro. Deve ser usada para "
                        "selecionar/agrupar compet\u00eancia e nunca deve ser inferida "
                        "de data_ref.",
                    ),
                    field(
                        "data_ref",
                        "Date_Ref",
                        "string",
                        False,
                        "YYYY-MM-DD",
                        "Normalized Date_Ref value from the source.",
                    ),
                    field(
                        "data_venda",
                        None,
                        "string",
                        True,
                        "YYYY-MM-DD",
                        "Data real da venda quando disponibilizada pela fonte; null quando "
                        "Date_Ref representa somente a refer\u00eancia mensal.",
                    ),
                    field("cod_marca", "Cod_Marca", "integer", False, None, "Brand code."),
                    field(
                        "descr_marca",
                        "Descr_Marca",
                        "string",
                        False,
                        None,
                        "Brand description.",
                    ),
                    field("cod_loja", "Cod_Loja", "integer", False, None, "Store code."),
                    field("descr_loja", "Descr_Loja", "string", False, None, "Store description."),
                    field(
                        "matricula",
                        "Matricula",
                        "string",
                        False,
                        None,
                        "Employee identifier preserved as text.",
                    ),
                    field(
                        "vlr_venda",
                        "Vlr _Venda",
                        "number",
                        False,
                        None,
                        "Source sale value preserved without two-decimal rounding.",
                    ),
                ],
            },
            "comissoes": {
                "file": "comissoes.jsonl",
                "fields": [
                    field(
                        "competencia",
                        None,
                        "string",
                        False,
                        "YYYY-MM",
                        "Explicit source manifest competency.",
                    ),
                    field("cod_marca", "Cod_Marca", "integer", False, None, "Brand code."),
                    field(
                        "descr_marca",
                        "Descr_Marca",
                        "string",
                        False,
                        None,
                        "Brand description.",
                    ),
                    field("cod_cargo", "Cod_Cargo", "integer", False, None, "Role code."),
                    field(
                        "descr_cargo",
                        "Descri_Cargo",
                        "string",
                        False,
                        None,
                        "Role description.",
                    ),
                    field(
                        "percentual_comissao",
                        "%_Comiss",
                        "number",
                        False,
                        None,
                        "Fra\u00e7\u00e3o decimal; 0.025 representa 2,5%.",
                    ),
                ],
            },
        },
    }


def field(
    name: str,
    source: str | None,
    type_name: str,
    nullable: bool,
    format_name: str | None,
    semantics: str,
) -> JsonObject:
    result: JsonObject = {
        "name": name,
        "source": source,
        "type": type_name,
        "nullable": nullable,
        "semantics": semantics,
    }
    if format_name is not None:
        result["format"] = format_name
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the canonical Dom Rock dataset.")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_dataset(source_root=args.source_root, output_dir=args.output_dir)
    print(json.dumps(result.hashes, sort_keys=True))


if __name__ == "__main__":
    main()
