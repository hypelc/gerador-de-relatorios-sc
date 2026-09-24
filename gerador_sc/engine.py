"""Servico de aplicacao que liga importacao, validacao, renderizacao e exportacao."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Callable

from .importers import inspect_file, remap_table
from .models import Diagnostic, ImportResult, ReportArtifact, ReportConfig, ReportValidationError
from .rendering import render_report


ProgressCallback = Callable[[int, str], None]


class OperationCancelled(RuntimeError):
    """Sinaliza cancelamento cooperativo de uma operacao em segundo plano."""


def validate_report(result: ImportResult, config: ReportConfig) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    if not config.table_ids:
        diagnostics.append(Diagnostic("error", "NO_TABLE_SELECTED", "Selecione pelo menos uma tabela para o relatorio.", "Conferir dados"))
    if len(set(config.table_ids)) != len(config.table_ids):
        diagnostics.append(
            Diagnostic(
                "error",
                "DUPLICATE_TABLE_SELECTED",
                "A mesma tabela foi selecionada mais de uma vez.",
                "Montar relatorio",
                "Selecione cada tabela somente uma vez.",
            )
        )
    if config.years and (
        any(isinstance(year, bool) or not isinstance(year, int) for year in config.years)
        or len(set(config.years)) != len(config.years)
        or tuple(config.years) != tuple(sorted(config.years))
    ):
        diagnostics.append(
            Diagnostic(
                "error",
                "YEARS_NOT_ORDERED",
                "Os anos selecionados devem ser inteiros, unicos e estar em ordem crescente.",
                "Montar relatorio",
                "Escolha cada ano uma vez e mantenha a ordem cronologica.",
            )
        )
    selected = []
    for table_id in config.table_ids:
        try:
            table = result.table(table_id)
        except KeyError:
            diagnostics.append(Diagnostic("error", "UNKNOWN_TABLE", "Uma tabela selecionada nao existe mais na importacao atual.", table_id, "Volte a conferencia e selecione novamente."))
            continue
        selected.append(table)
        if not table.valid:
            diagnostics.append(Diagnostic("error", "INVALID_TABLE_SELECTED", f"A tabela '{table.title}' ainda possui problemas que impedem a geracao.", table.source_sheet, "Corrija o arquivo ou ajuste o mapeamento antes de continuar."))
    unconfirmed = [
        table
        for table in result.tables
        if not table.valid and table.table_id not in config.table_ids and table.table_id not in config.confirmed_exclusions
    ]
    if unconfirmed:
        diagnostics.append(Diagnostic("error", "EXCLUSION_NOT_CONFIRMED", "Existe uma tabela com problema que foi deixada fora sem confirmacao explicita.", ", ".join(table.source_sheet for table in unconfirmed), "Confirme a exclusao na etapa Conferir dados ou corrija o mapeamento."))
    if not config.title.strip():
        diagnostics.append(Diagnostic("error", "TITLE_REQUIRED", "Informe um titulo para identificar o PDF.", "Montar relatorio"))
    if not config.years:
        diagnostics.append(Diagnostic("error", "NO_YEAR_SELECTED", "Selecione pelo menos um ano.", "Montar relatorio"))
    for table in selected:
        missing_years = sorted(set(config.years) - set(table.years))
        if missing_years:
            diagnostics.append(Diagnostic("error", "YEAR_NOT_AVAILABLE", f"Os anos {', '.join(map(str, missing_years))} nao existem na tabela '{table.title}'.", table.source_sheet, "Escolha somente anos comuns as tabelas selecionadas."))
    if config.model not in {"paineis", "linhas", "mapa", "barras", "pizza"}:
        diagnostics.append(Diagnostic("error", "UNKNOWN_MODEL", "Modelo de relatorio desconhecido.", config.model))
    if config.model in {"barras", "pizza"} and len(config.years) != 1:
        diagnostics.append(Diagnostic("error", "ONE_YEAR_REQUIRED", "Barras e pizza comparam um ano por vez.", "Montar relatorio", "Selecione um unico ano."))
    if config.model == "pizza":
        for table in selected:
            if table.indicator_type not in {"nascidos", "mortalidade"}:
                diagnostics.append(Diagnostic("error", "PIE_REQUIRES_COUNTS", "Pizza so representa contagens que compoem um total; taxas e coberturas nao podem ser somadas.", table.source_sheet))
            elif len(config.years) == 1:
                index = table.years.index(config.years[0]) if config.years[0] in table.years else None
                values = [serie.values[index] for serie in table.series] if index is not None else []
                if any(value is None or value < 0 for value in values) or sum(value for value in values if value is not None) <= 0 or len(values) < 2:
                    diagnostics.append(Diagnostic("error", "PIE_INVALID_VALUES", "Pizza exige pelo menos duas contagens nao negativas, sem lacunas, com total positivo.", table.source_sheet))
    if config.model == "mapa":
        if len(selected) != 1:
            diagnostics.append(Diagnostic("error", "MAP_REQUIRES_ONE_TABLE", "O mapa usa uma tabela por vez.", "Montar relatorio", "Selecione uma tabela de cobertura vacinal."))
        elif not selected[0].map_ready:
            diagnostics.append(Diagnostic("error", "MAP_CONTRACT_NOT_MET", "O mapa exige cobertura vacinal e codigos unicos de macrorregioes de saude de Santa Catarina.", selected[0].source_sheet, "Use somente os codigos 4210, 4211, 4213, 4214, 4215, 4216, 4217 e 4218; regioes nao presentes serao marcadas como sem dados."))
        else:
            for year in config.years:
                if year in selected[0].years:
                    position = selected[0].years.index(year)
                    if all(serie.values[position] is None for serie in selected[0].series):
                        diagnostics.append(Diagnostic("error", "MAP_YEAR_WITHOUT_DATA", f"Nenhuma macrorregiao possui valor em {year}.", selected[0].source_sheet, "Escolha um ano com pelo menos um valor informado."))
    return tuple(diagnostics)


class ReportService:
    """Fachada sem dependencia de Qt para o fluxo principal do produto."""

    def inspect(self, path: str | Path) -> ImportResult:
        return inspect_file(path)

    def remap(
        self,
        result: ImportResult,
        table_id: str,
        *,
        header_row: int | None = None,
        label_column: int | None = None,
        unit: str = "",
        indicator_type=None,
    ) -> ImportResult:
        return remap_table(result, table_id, header_row=header_row, label_column=label_column, unit=unit, indicator_type=indicator_type)

    def validate(self, result: ImportResult, config: ReportConfig) -> tuple[Diagnostic, ...]:
        return validate_report(result, config)

    def preview(
        self,
        result: ImportResult,
        config: ReportConfig,
        *,
        progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ReportArtifact:
        diagnostics = self.validate(result, config)
        errors = tuple(diagnostic for diagnostic in diagnostics if diagnostic.severity == "error")
        if errors:
            raise ReportValidationError(errors)
        selected = tuple(result.table(table_id) for table_id in config.table_ids)
        session_dir = Path(tempfile.mkdtemp(prefix="gerador-sc-"))
        pdf_path = session_dir / "relatorio.pdf"
        preview_dir = session_dir / "preview"
        try:
            previews, page_count = render_report(
                selected,
                config,
                pdf_path,
                preview_dir,
                result.source_path.name,
                progress=progress,
                cancel_event=cancel_event,
            )
        except Exception:
            shutil.rmtree(session_dir, ignore_errors=True)
            raise
        return ReportArtifact(pdf_path, preview_dir, previews, page_count, config)

    def export(
        self,
        artifact: ReportArtifact,
        destination: str | Path,
        *,
        overwrite: bool = False,
        progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        raw_destination = str(destination).strip()
        if not raw_destination:
            raise ValueError("Informe um destino para o PDF antes de exportar.")
        target = Path(raw_destination).expanduser().resolve()
        if target.exists() and target.is_dir():
            raise ValueError("O destino escolhido e uma pasta. Informe o nome do arquivo PDF.")
        if target.suffix.lower() != ".pdf":
            target = target.with_suffix(".pdf")
        if target.exists() and not overwrite:
            raise FileExistsError(f"O arquivo ja existe: {target}")
        if not artifact.pdf_path.exists():
            raise FileNotFoundError("A pre-visualizacao foi removida antes da exportacao.")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
        try:
            if progress:
                progress(15, "Copiando o PDF para o destino")
            if cancel_event is not None and cancel_event.is_set():
                raise OperationCancelled("Exportacao cancelada pela pessoa usuaria.")
            total_size = artifact.pdf_path.stat().st_size
            copied_size = 0
            with artifact.pdf_path.open("rb") as source_file, temporary.open("wb") as target_file:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise OperationCancelled("Exportacao cancelada pela pessoa usuaria.")
                    chunk = source_file.read(1024 * 1024)
                    if not chunk:
                        break
                    target_file.write(chunk)
                    copied_size += len(chunk)
                    if progress:
                        copied_percent = 15 + int((copied_size / max(total_size, 1)) * 60)
                        progress(min(copied_percent, 75), "Copiando o PDF para o destino")
            if progress:
                progress(75, "Finalizando o arquivo")
            if cancel_event is not None and cancel_event.is_set():
                raise OperationCancelled("Exportacao cancelada pela pessoa usuaria.")
            os.replace(temporary, target)
            if progress:
                progress(100, "PDF exportado")
        finally:
            if temporary.exists():
                temporary.unlink()
        return target

    def cleanup(self, artifact: ReportArtifact | None) -> None:
        if artifact:
            session_dir = artifact.pdf_path.parent
            if session_dir.name.startswith("gerador-sc-"):
                shutil.rmtree(session_dir, ignore_errors=True)


def default_export_path(result: ImportResult) -> Path:
    return result.source_path.with_name(f"{result.source_path.stem}_relatorio.pdf")
