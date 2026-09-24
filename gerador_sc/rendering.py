"""Renderizadores de graficos, mapas, pre-visualizacao e PDF consolidado."""

from __future__ import annotations

import math
import re
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as MplPath
import matplotlib.patheffects as effects
from matplotlib.ticker import FuncFormatter, MaxNLocator

from .geography import MAP_BANDS, MAP_CODES, MAP_COLORS, MAP_NAMES, band, load_projected_geometries
from .models import RecognizedTable, ReportConfig, Series


PALETTES = {
    "Acessivel": ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#8C6D00", "#56B4E9", "#332288", "#555555", "#AA4499"),
    "Azul e verde": ("#005F73", "#0A9396", "#94D2BD", "#E9D8A6", "#CA6702", "#BB3E03", "#AE2012", "#3A5A40", "#588157"),
    "Neutros": ("#1D3557", "#457B9D", "#6C757D", "#8D99AE", "#495057", "#343A40", "#2B2D42", "#6D597A", "#577590"),
}
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "h", "*")


class RenderCancelled(Exception):
    """Sinaliza cancelamento solicitado pela interface."""


ProgressCallback = Callable[[int, str], None]


def _check_cancel(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RenderCancelled("Geracao cancelada pela pessoa usuaria.")


def _progress(progress: ProgressCallback | None, value: int, message: str) -> None:
    if progress:
        progress(max(0, min(100, value)), message)


def _normalise_name(value: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _normalise_name(value).lower()).strip("_") or "pagina"


def _series_name(serie: Series) -> str:
    return re.sub(r"^\d{4}\s*", "", serie.name).strip().upper() or serie.name


def _values_for_years(table: RecognizedTable, selected_years: tuple[int, ...], serie: Series) -> list[float | None]:
    indexes = [table.years.index(year) for year in selected_years]
    return [serie.values[index] for index in indexes]


def _unit(table: RecognizedTable, config: ReportConfig) -> str:
    return config.unit.strip() or table.unit


def _indicator(table: RecognizedTable, config: ReportConfig) -> str:
    return config.indicator_name.strip() or table.title


def _format_selected_years(years: tuple[int, ...]) -> str:
    return ", ".join(str(year) for year in years)


def _format_year_columns(columns: tuple[int, ...]) -> str:
    if not columns:
        return "nenhuma"
    if columns == tuple(range(columns[0], columns[-1] + 1)):
        return f"{columns[0]}-{columns[-1]}"
    return ", ".join(str(column) for column in columns)


def _maximum(table: RecognizedTable, selected_years: tuple[int, ...]) -> float:
    values = [
        value
        for serie in table.series
        for value in _values_for_years(table, selected_years, serie)
        if value is not None
    ]
    return max(values, default=1.0)


def _format_value(value: float, table: RecognizedTable) -> str:
    if table.indicator_type == "vacina":
        return f"{value:.2f}%".replace(".", ",")
    return f"{value:,.0f}".replace(",", ".")


def _missing_note(table: RecognizedTable, selected_years: tuple[int, ...]) -> str:
    missing = []
    for year in selected_years:
        if any(_values_for_years(table, (year,), serie)[0] is None for serie in table.series):
            missing.append(str(year))
    return "Dados ausentes em parte ou em todas as series: " + ", ".join(missing) + ". Lacunas sem interpolacao." if missing else ""


def _chart_figure(table: RecognizedTable, config: ReportConfig) -> tuple[plt.Figure, bool]:
    selected_years = config.years
    panel = config.model == "paineis" and len(table.series) > 1
    quantity = len(table.series)
    if panel:
        columns = 2 if quantity <= 8 else 4
        rows = math.ceil(quantity / columns)
        fig, grid = plt.subplots(rows, columns, figsize=(14 if columns == 2 else 18, 3 * rows + 2), squeeze=False)
        axes = list(grid.flat)
        fig.subplots_adjust(left=0.08, right=0.95, top=0.80, bottom=0.13, hspace=0.67, wspace=0.22)
    else:
        fig, axis = plt.subplots(figsize=(14, 8))
        fig.subplots_adjust(left=0.08, right=0.67, top=0.77, bottom=0.20)
        axes = [axis]
    maximum = _maximum(table, selected_years)
    if table.indicator_type == "vacina":
        upper = max(20, math.ceil(maximum / 20) * 20)
    else:
        upper = max(1, maximum * 1.15)
    colors = PALETTES.get(config.palette, PALETTES["Acessivel"])
    for index, serie in enumerate(table.series):
        axis = axes[index] if panel else axes[0]
        values = _values_for_years(table, selected_years, serie)
        color = colors[index % len(colors)]
        marker = MARKERS[index % len(MARKERS)]
        axis.plot(
            selected_years,
            [float("nan") if value is None else value for value in values],
            label=textwrap.fill(_series_name(serie), 30),
            color=color,
            marker=marker,
            markersize=5,
            linewidth=2,
        )
        if panel:
            axis.set_title(textwrap.fill(_series_name(serie), 40), loc="left", fontsize=11, weight="bold", pad=12)
            if values and values[-1] is not None:
                axis.annotate(
                    _format_value(values[-1], table),
                    (selected_years[-1], values[-1]),
                    xytext=(0, 10),
                    textcoords="offset points",
                    ha="center",
                    fontsize=9,
                    color=color,
                )
    for axis in axes[: quantity if panel else 1]:
        axis.set_xticks(selected_years)
        axis.tick_params(axis="x", labelsize=9, rotation=45 if panel and len(selected_years) > 8 else 0)
        axis.set_xlabel("Ano", labelpad=7)
        axis.set_ylim(0, upper)
        axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}".replace(",", ".")))
        axis.yaxis.set_major_locator(MaxNLocator(nbins=5 if panel else 7, integer=True))
        axis.grid(axis="y", color="#E0E5EB", linewidth=0.7)
        axis.set_axisbelow(True)
    if panel:
        fig.supylabel(_unit(table, config), x=0.02, fontsize=12)
        for axis in axes[quantity:]:
            axis.set_visible(False)
    else:
        axes[0].set_ylabel(_unit(table, config), labelpad=12)
        axes[0].legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=9 if quantity > 10 else 10, labelspacing=0.85)
    return fig, panel


def _chart_header(fig: plt.Figure, table: RecognizedTable, config: ReportConfig, panel: bool, source_name: str) -> None:
    fig.text(0.08, 0.94 if panel else 0.93, "SANTA CATARINA", fontsize=11, color="#52606D", weight="bold")
    fig.text(0.08, 0.90 if panel else 0.875, _indicator(table, config), fontsize=18, weight="bold", color="#162B40")
    subtitle = f"{config.years[0]} - {config.years[-1]} | " + ("Por macrorregiao de saude" if len(table.series) > 1 else "Serie selecionada")
    if panel:
        subtitle += " | Mesma escala em todos os paineis"
    fig.text(0.08, 0.865 if panel else 0.83, subtitle, color="#52606D")
    notes = [f"Fonte do arquivo: {source_name} | Aba: {table.source_sheet.strip()}"]
    missing = _missing_note(table, config.years)
    if missing:
        notes.append(missing)
    if table.indicator_type == "vacina":
        notes.append("Valores originais; coberturas acima de 100% preservadas. Colunas de media e total excluidas.")
    elif table.indicator_type == "mortalidade":
        notes.append("Valores absolutos da planilha; nao representam uma taxa por mil nascidos vivos.")
    fig.text(0.08, 0.04, "\n".join(notes), fontsize=8.5, color="#52606D", linespacing=1.55)


def _polygons(geometry):
    return [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)


def _draw_map(axis, geometries: dict[str, object], values: dict[str, float | None], identify: bool = True) -> None:
    for number, code in enumerate(MAP_CODES, 1):
        category = band(values[code])
        color = "#DDDDDD" if category is None else MAP_COLORS[category]
        for polygon in _polygons(geometries[code]):
            vertices = []
            commands = []
            for ring in [polygon.exterior, *polygon.interiors]:
                points = list(ring.coords)
                vertices.extend(points)
                commands.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(points) - 2) + [MplPath.CLOSEPOLY])
            axis.add_patch(PathPatch(MplPath(vertices, commands), facecolor=color, edgecolor="#343A35", linewidth=0.65, hatch="///" if category is None else None))
        if identify:
            center = max(_polygons(geometries[code]), key=lambda polygon: polygon.area).representative_point()
            label = axis.text(center.x, center.y, str(number), ha="center", va="center", weight="bold", fontsize=10, color="#17251C")
            label.set_path_effects([effects.withStroke(linewidth=2.5, foreground="white")])
    bounds = [geometry.bounds for geometry in geometries.values()]
    minimum_x = min(item[0] for item in bounds)
    minimum_y = min(item[1] for item in bounds)
    maximum_x = max(item[2] for item in bounds)
    maximum_y = max(item[3] for item in bounds)
    axis.set_xlim(minimum_x - 15000, maximum_x + 15000)
    axis.set_ylim(minimum_y - 15000, maximum_y + 15000)
    axis.set_aspect("equal")
    axis.axis("off")


def _map_values(table: RecognizedTable, year: int) -> dict[str, float | None]:
    position = table.years.index(year)
    values: dict[str, float | None] = {}
    for serie in table.series:
        code = serie.code
        if code in values:
            raise ValueError(f"Codigo geografico repetido: {code}")
        values[code] = serie.values[position]
    if set(values) != set(MAP_CODES):
        raise ValueError("A tabela do mapa precisa conter as oito macrorregioes de saude de Santa Catarina.")
    return values


def _map_figure(table: RecognizedTable, config: ReportConfig, year: int, geometries: dict[str, object], source_name: str) -> plt.Figure:
    fig = plt.figure(figsize=(14, 10))
    fig.text(0.055, 0.95, config.title, fontsize=20, weight="bold", color="#162B40")
    fig.text(0.055, 0.915, f"{_indicator(table, config)} | Santa Catarina | {year}", fontsize=12, color="#52606D")
    axis = fig.add_axes([0.08, 0.28, 0.84, 0.58])
    _draw_map(axis, geometries, _map_values(table, year))
    axis.set_title("Macrorregioes de saude", loc="left", fontsize=14, weight="bold", pad=13)
    handles = [Patch(facecolor=color, edgecolor="#555", label=label) for color, label in zip(MAP_COLORS, MAP_BANDS)]
    handles.append(Patch(facecolor="#DDDDDD", edgecolor="#555", hatch="///", label="Sem dado"))
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.225), ncol=5, frameon=False, title="Cobertura vacinal (%)")
    map_values = _map_values(table, year)
    rows = [[f"{number}. {MAP_NAMES[code]}", "Sem dado" if map_values[code] is None else _format_value(map_values[code], table)] for number, code in enumerate(MAP_CODES, 1)]
    table_axis = fig.add_axes([0.17, 0.085, 0.66, 0.14])
    table_axis.axis("off")
    report_table = table_axis.table(cellText=rows, colLabels=["Macrorregiao de saude", "Valor"], colWidths=[0.72, 0.28], cellLoc="left", bbox=[0, 0, 1, 1])
    report_table.auto_set_font_size(False)
    report_table.set_fontsize(9)
    for (row, column), cell in report_table.get_celld().items():
        cell.set_edgecolor("white")
        cell.set_facecolor("#E9EEF1" if row == 0 else "#F5F7F8" if row % 2 else "white")
        if row == 0:
            cell.set_text_props(weight="bold")
    footer = [f"Arquivo de origem: {source_name}"]
    if config.authors.strip():
        footer.append(f"Autores: {config.authors.strip()}")
    if config.source.strip():
        footer.append(f"Fonte informada: {config.source.strip()}")
    footer.append("Geografia: limites municipais do IBGE e composicao das macrorregioes publicada pelo Ministerio da Saude.")
    fig.text(0.055, 0.018, "\n".join(footer), fontsize=8, color="#52606D")
    return fig


def _methodology_page(tables: tuple[RecognizedTable, ...], config: ReportConfig, source_name: str) -> plt.Figure:
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.text(0.08, 0.90, "Metodologia e origem dos dados", fontsize=21, weight="bold", color="#162B40")
    selected_years = _format_selected_years(config.years)
    effective_units = ", ".join(dict.fromkeys(_unit(table, config) for table in tables))
    effective_indicators = ", ".join(dict.fromkeys(_indicator(table, config) for table in tables))
    metadata = "\n".join(
        textwrap.fill(line, 105)
        for line in (
            f"Relatorio: {config.title}",
            f"Autores: {config.authors.strip() or 'Nao informados'}",
            f"Gerado em: {datetime.now().astimezone().strftime('%d/%m/%Y %H:%M')}",
            f"Arquivo de origem: {source_name}",
            f"Fonte informada: {config.source.strip() or 'Nao informada'}",
            f"Anos selecionados: {selected_years}",
            f"Unidades utilizadas: {effective_units or 'Nao informadas'}",
            f"Indicadores utilizados: {effective_indicators or 'Nao informados'}",
        )
    )
    fig.text(0.08, 0.84, metadata, fontsize=8.8, color="#273444", va="top", linespacing=1.05)
    introduction = "\n".join(
        textwrap.fill(paragraph, 112)
        for paragraph in (
            "Relatorio elaborado pelo Gerador de Relatorios SC a partir das colunas de identificacao, anos e valores confirmadas durante a importacao.",
            "Os valores foram mantidos conforme o arquivo fornecido; celulas vazias nao foram convertidas em zero. Os graficos foram produzidos em Python com Matplotlib.",
        )
    )
    fig.text(0.08, 0.54, introduction, fontsize=9.2, color="#273444", va="top", linespacing=1.1)
    fig.text(0.08, 0.42, "Colunas de origem confirmadas:", fontsize=10.5, color="#273444", weight="bold")
    fields = [
        f"{table.source_sheet.strip()}: ID {table.label_column}, cabecalho {table.header_row}, anos col. {_format_year_columns(table.year_columns)}."
        for table in tables
    ]
    if len(fields) <= 12:
        fig.text(0.08, 0.385, "\n".join(textwrap.fill(line, 112) for line in fields), fontsize=8.8, color="#273444", va="top", linespacing=1.05)
        note_y = 0.13
    else:
        middle = (len(fields) + 1) // 2
        columns = [fields[:middle], fields[middle:]]
        for x, column in zip((0.08, 0.53), columns):
            compact = "\n".join(textwrap.fill(line, 70) for line in column)
            fig.text(x, 0.385, compact, fontsize=8.2, color="#273444", va="top", linespacing=1.05)
        note_y = 0.08
    notes = ["Abas ou tabelas nao selecionadas permanecem fora do relatorio. Problemas e dados ausentes foram preservados na conferencia."]
    if config.model == "mapa":
        notes.insert(0, "Mapas: limites municipais do IBGE e composicao das macrorregioes publicada pelo Ministerio da Saude. Os valores representam a macrorregiao, nao dados municipais.")
    fig.text(0.08, note_y, "\n".join(textwrap.fill(note, 112) for note in notes), fontsize=9.2, color="#52606D", va="top", linespacing=1.3)
    processing = "Processamento no servidor, sem armazenamento permanente." if config.processing_context == "web" else "Processamento local, sem servidor."
    fig.text(0.08, 0.025, f"Gerador de Relatorios SC | Versao 0.1.0 | {processing}", fontsize=9, color="#52606D")
    return fig


def render_report(
    tables: tuple[RecognizedTable, ...],
    config: ReportConfig,
    output_pdf: Path,
    preview_dir: Path,
    source_name: str,
    *,
    progress: ProgressCallback | None = None,
    cancel_event=None,
) -> tuple[tuple[Path, ...], int]:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
    preview_images: list[Path] = []
    page_number = 0
    total_pages = len(tables) if config.model != "mapa" else len(tables) * len(config.years)
    total_pages += 1
    geometries = load_projected_geometries() if config.model == "mapa" else None
    with PdfPages(output_pdf) as pdf:
        pdf.infodict().update({"Title": config.title, "Author": config.authors, "Subject": "Relatorio de indicadores de Santa Catarina", "Creator": "Gerador de Relatorios SC"})
        for table in tables:
            if config.model == "mapa":
                for year in config.years:
                    _check_cancel(cancel_event)
                    page_number += 1
                    _progress(progress, int(page_number / total_pages * 100), f"Gerando mapa de {table.title} ({year})")
                    figure = _map_figure(table, config, year, geometries or {}, source_name)
                    preview = preview_dir / f"{page_number:03d}_{_safe_slug(table.title)}_{year}.png"
                    figure.savefig(preview, dpi=130, facecolor="white")
                    pdf.savefig(figure, facecolor="white")
                    preview_images.append(preview)
                    plt.close(figure)
            else:
                _check_cancel(cancel_event)
                page_number += 1
                _progress(progress, int(page_number / total_pages * 100), f"Gerando {table.title}")
                figure, panel = _chart_figure(table, config)
                _chart_header(figure, table, config, panel, source_name)
                preview = preview_dir / f"{page_number:03d}_{_safe_slug(table.title)}.png"
                figure.savefig(preview, dpi=130, facecolor="white")
                pdf.savefig(figure, facecolor="white")
                preview_images.append(preview)
                plt.close(figure)
        _check_cancel(cancel_event)
        page_number += 1
        _progress(progress, 98, "Registrando metodologia")
        figure = _methodology_page(tables, config, source_name)
        preview = preview_dir / f"{page_number:03d}_metodologia.png"
        figure.savefig(preview, dpi=130, facecolor="white")
        pdf.savefig(figure, facecolor="white")
        preview_images.append(preview)
        plt.close(figure)
    _progress(progress, 100, "Relatorio pronto")
    return tuple(preview_images), page_number
