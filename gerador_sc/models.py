"""Modelos de dados usados pelo motor e apresentados pela interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


Severity = Literal["info", "warning", "error"]
IndicatorType = Literal["vacina", "nascidos", "mortalidade", "contagem", "desconhecido"]
SC_MACRO_CODES = frozenset({"4210", "4211", "4213", "4214", "4215", "4216", "4217", "4218"})


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    code: str
    message: str
    location: str = ""
    suggestion: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "location": self.location,
            "suggestion": self.suggestion,
        }


@dataclass(frozen=True)
class Series:
    name: str
    values: tuple[float | None, ...]
    source_row: int

    @property
    def code(self) -> str:
        return self.name.strip().split(maxsplit=1)[0] if self.name.strip() else ""

    def to_dict(self, years: tuple[int, ...]) -> dict[str, object]:
        return {
            "nome": self.name,
            "codigo": self.code,
            "valores": list(self.values),
            "linha": self.source_row,
            "pontos": [
                {"ano": year, "valor": value}
                for year, value in zip(years, self.values)
            ],
        }


@dataclass(frozen=True)
class RecognizedTable:
    table_id: str
    source_sheet: str
    title: str
    header_row: int
    label_column: int
    years: tuple[int, ...]
    year_columns: tuple[int, ...]
    series: tuple[Series, ...]
    unit: str
    indicator_type: IndicatorType
    diagnostics: tuple[Diagnostic, ...] = ()
    confidence: float = 0.0
    layout: str = "horizontal"

    @property
    def valid(self) -> bool:
        return bool(self.series) and not any(
            diagnostic.severity == "error" for diagnostic in self.diagnostics
        )

    @property
    def map_ready(self) -> bool:
        codes = [serie.code for serie in self.series]
        return (
            self.valid
            and
            self.indicator_type == "vacina"
            and bool(codes)
            and len(set(codes)) == len(codes)
            and set(codes) <= SC_MACRO_CODES
        )

    @property
    def missing_years(self) -> tuple[int, ...]:
        return tuple(
            year
            for index, year in enumerate(self.years)
            if any(serie.values[index] is None for serie in self.series)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.table_id,
            "aba": self.source_sheet,
            "titulo": self.title,
            "cabecalho": self.header_row,
            "coluna_identificacao": self.label_column,
            "anos": list(self.years),
            "colunas_anos": list(self.year_columns),
            "series": [serie.to_dict(self.years) for serie in self.series],
            "unidade": self.unit,
            "tipo_indicador": self.indicator_type,
            "valida": self.valid,
            "mapa_disponivel": self.map_ready,
            "regioes_mapeadas": len(self.series) if self.map_ready else 0,
            "confianca": self.confidence,
            "estrutura": self.layout,
            "diagnosticos": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


@dataclass(frozen=True)
class SheetSummary:
    name: str
    table_count: int
    status: str
    message: str


@dataclass(frozen=True)
class SourceSheet:
    name: str
    rows: tuple[tuple[object, ...], ...]
    formulas: dict[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class CategoricalTable:
    table_id: str
    source_sheet: str
    title: str
    header_row: int
    label_column: int
    value_column: int
    categories: tuple[tuple[str, float], ...]
    state_value: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.table_id, "aba": self.source_sheet, "titulo": self.title,
            "cabecalho": self.header_row, "coluna_identificacao": self.label_column,
            "coluna_valor": self.value_column, "categorias": [
                {"nome": name, "valor": value} for name, value in self.categories
            ], "valor_estado": self.state_value, "valida": bool(self.categories),
        }


@dataclass(frozen=True)
class ImportResult:
    source_path: Path
    file_format: Literal["xlsx", "csv"]
    source_sha256: str
    tables: tuple[RecognizedTable, ...]
    sheets: tuple[SourceSheet, ...] = field(default_factory=tuple, repr=False)
    sheet_summaries: tuple[SheetSummary, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    formula_count: int = 0
    categorical_tables: tuple[CategoricalTable, ...] = ()

    @property
    def valid_tables(self) -> tuple[RecognizedTable, ...]:
        return tuple(table for table in self.tables if table.valid)

    def table(self, table_id: str) -> RecognizedTable:
        for table in self.tables:
            if table.table_id == table_id:
                return table
        raise KeyError(f"Tabela nao encontrada: {table_id}")

    def to_dict(self) -> dict[str, object]:
        return {
            "arquivo": self.source_path.name,
            "formato": self.file_format,
            "sha256": self.source_sha256,
            "formulas": self.formula_count,
            "abas": [
                {
                    "nome": summary.name,
                    "tabelas": summary.table_count,
                    "status": summary.status,
                    "mensagem": summary.message,
                }
                for summary in self.sheet_summaries
            ],
            "tabelas": [table.to_dict() for table in self.tables],
            "tabelas_categoricas": [table.to_dict() for table in self.categorical_tables],
            "diagnosticos": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


@dataclass(frozen=True)
class ReportConfig:
    table_ids: tuple[str, ...]
    model: Literal["paineis", "linhas", "mapa", "barras", "pizza"] = "paineis"
    years: tuple[int, ...] = ()
    title: str = "Relatorio de indicadores de Santa Catarina"
    authors: str = ""
    source: str = ""
    indicator_name: str = ""
    unit: str = ""
    palette: str = "Acessivel"
    confirmed_exclusions: tuple[str, ...] = ()
    processing_context: Literal["local", "web"] = "local"


@dataclass(frozen=True)
class ReportArtifact:
    pdf_path: Path
    preview_dir: Path
    preview_images: tuple[Path, ...]
    page_count: int
    config: ReportConfig


class ReportValidationError(ValueError):
    """Erro contendo diagnosticos que podem ser mostrados pela interface."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]):
        self.diagnostics = diagnostics
        super().__init__("; ".join(diagnostic.message for diagnostic in diagnostics))
