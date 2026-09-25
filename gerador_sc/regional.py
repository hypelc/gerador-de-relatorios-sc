from __future__ import annotations

import csv
import io
import json
import math
import re
import textwrap
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.patheffects as effects
import matplotlib.pyplot as plt
import openpyxl
from matplotlib.cm import ScalarMappable
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as MplPath
from pyproj import Transformer
from shapely.geometry import shape
from shapely.geometry.polygon import orient
from shapely.ops import transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
GEO_DIR = ROOT / "geodados"


@dataclass(frozen=True)
class RegionalConfig:
    title: str
    authors: str = ""
    source: str = ""
    unit: str = ""
    period: str = ""
    processing_context: str = "web"


def normalize_name(value: str) -> str:
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.strip())
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", text).upper()


def format_rate(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _number(value: object, label: str) -> float:
    if isinstance(value, str):
        value = value.strip()
        if value.count(",") == 1 and "." not in value:
            value = value.replace(",", ".")
        try:
            value = float(value)
        except ValueError as error:
            raise ValueError(f"Valor nao numerico para {label}: {value!r}.") from error
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"Valor invalido para {label}: {value!r}.")
    return float(value)


def _rows(path: Path) -> tuple[str, list[tuple[object, ...]]]:
    if path.suffix.lower() == ".xlsx":
        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            if len(workbook.worksheets) != 1:
                raise ValueError(
                    "O modelo das 17 Regionais exige uma planilha com uma única aba de dados."
                )
            sheet = workbook.active
            return sheet.title, list(sheet.iter_rows(values_only=True))
        finally:
            workbook.close()
    if path.suffix.lower() == ".csv":
        raw = path.read_text(encoding="utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(raw[:4096], delimiters=";,\t")
        except csv.Error:
            dialect = csv.excel
        return path.stem, [tuple(row) for row in csv.reader(io.StringIO(raw), dialect)]
    raise ValueError("Formato nao suportado. Use .xlsx ou .csv.")


def read_values(
    path: str | Path,
) -> tuple[dict[str, tuple[str, float | None]], float | None, str, str]:
    source = Path(path)
    sheet_name, rows = _rows(source)
    if (
        not rows
        or len(rows[0]) < 2
        or normalize_name(str(rows[0][0] or "")) != "REGIONAIS"
    ):
        raise ValueError("A primeira coluna deve ter o cabecalho 'Regionais'.")
    indicator = str(rows[0][1] or "").strip()
    if not indicator:
        raise ValueError("A segunda coluna precisa informar o nome do indicador.")
    values: dict[str, tuple[str, float | None]] = {}
    state_value: float | None = None
    state_seen = False
    for row_number, row in enumerate(rows[1:], 2):
        regional = row[0] if row else None
        rate = row[1] if len(row) > 1 else None
        if regional is None and rate is None:
            continue
        display_name = str(regional or "").strip()
        if not display_name:
            raise ValueError(
                f"Falta o nome da regional na linha {row_number} da aba {sheet_name}."
            )
        name = normalize_name(display_name)
        number = (
            None
            if rate is None or (isinstance(rate, str) and not rate.strip())
            else _number(rate, f"{display_name}, linha {row_number} da aba {sheet_name}")
        )
        if name == "SANTA CATARINA":
            if state_seen:
                raise ValueError("A linha Santa Catarina aparece mais de uma vez.")
            state_seen = True
            state_value = number
        else:
            if name in values:
                raise ValueError(
                    f"Regional repetida: {display_name}, linha {row_number}."
                )
            values[name] = (display_name, number)
    metadata, _ = read_region_mapping()
    expected = {item["normalized_name"] for item in metadata.values()}
    extra = set(values) - expected
    if extra:
        raise ValueError(
            f"Regionais sem correspondencia geografica: {', '.join(sorted(extra))}."
        )
    if not any(value is not None for _, value in values.values()):
        raise ValueError(
            "Nenhuma Regional de Saude possui valor numerico; informe pelo menos uma Regional para gerar o mapa."
        )
    return values, state_value, indicator, sheet_name


def read_region_mapping() -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    metadata: dict[str, dict[str, str]] = {}
    municipalities: dict[str, list[str]] = {}
    with (GEO_DIR / "macrorregioes_ms.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            if row["sg_uf"] != "SC":
                continue
            code = row["cod_regiao_de_saude"]
            metadata[code] = {
                "name": row["regiao_de_saude"],
                "normalized_name": normalize_name(row["regiao_de_saude"]),
            }
            municipalities.setdefault(code, []).append(row["cod_municipio"])
    if len(metadata) != 17 or sum(map(len, municipalities.values())) != 295:
        raise ValueError(
            "A composicao geografica esperada deve ter 17 regionais e 295 municipios."
        )
    return metadata, municipalities


def build_geometries(municipalities: dict[str, list[str]]) -> dict[str, object]:
    payload = json.loads(
        (GEO_DIR / "sc_municipios_ibge.geojson").read_text(encoding="utf-8")
    )
    code_by_municipality = {
        municipality: region
        for region, region_municipalities in municipalities.items()
        for municipality in region_municipalities
    }
    groups = {code: [] for code in municipalities}
    seen: set[str] = set()
    for feature in payload["features"]:
        municipality = str(feature["properties"]["codarea"])[:6]
        if municipality not in code_by_municipality:
            raise ValueError(f"Municipio sem regional: {municipality}")
        geometry = shape(feature["geometry"])
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError(f"Geometria municipal invalida: {municipality}")
        groups[code_by_municipality[municipality]].append(geometry)
        seen.add(municipality)
    if seen != set(code_by_municipality):
        missing = sorted(set(code_by_municipality) - seen)
        raise ValueError(f"Municipios ausentes da malha: {missing}")
    projector = Transformer.from_crs("EPSG:4674", "EPSG:5880", always_xy=True)
    regions = {
        code: transform(projector.transform, unary_union(geometries))
        for code, geometries in groups.items()
    }
    if any(geometry.is_empty or not geometry.is_valid for geometry in regions.values()):
        raise ValueError("Uma regional resultou em geometria vazia ou invalida.")
    return regions


def polygons(geometry):
    return [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)


def geometry_patch(geometry, **kwargs) -> PathPatch:
    vertices = []
    codes = []
    for polygon in polygons(geometry):
        polygon = orient(polygon, sign=1)
        for ring in [polygon.exterior, *polygon.interiors]:
            points = list(ring.coords)
            vertices.extend(points)
            codes.extend(
                [MplPath.MOVETO]
                + [MplPath.LINETO] * (len(points) - 2)
                + [MplPath.CLOSEPOLY]
            )
    return PathPatch(MplPath(vertices, codes), **kwargs)


def draw_figure(
    metadata: dict[str, dict[str, str]],
    geometries: dict[str, object],
    values_by_name: dict[str, tuple[str, float | None]],
    state_value: float | None,
    indicator: str,
    config: RegionalConfig,
    source_name: str,
    pdf_output: Path,
    png_output: Path,
) -> None:
    records = []
    for number, code in enumerate(sorted(metadata), 1):
        normalized_name = metadata[code]["normalized_name"]
        source_record = values_by_name.get(normalized_name)
        records.append(
            {
                "number": number,
                "code": code,
                "name": metadata[code]["name"],
                "value": source_record[1] if source_record else None,
                "geometry": geometries[code],
            }
        )
    expected = {item["normalized_name"] for item in metadata.values()}
    extra = set(values_by_name) - expected
    if extra:
        raise ValueError(
            f"Regionais da planilha sem correspondencia geografica: {sorted(extra)}"
        )

    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "pdf.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    observed = [record["value"] for record in records if record["value"] is not None]
    if state_value is not None:
        observed.append(state_value)
    minimum = min(observed)
    maximum = max(observed)
    if minimum == maximum:
        minimum -= 0.5
        maximum += 0.5
    normalizer = mpl.colors.Normalize(vmin=minimum, vmax=maximum)
    colormap = mpl.colormaps["viridis"]

    figure = plt.figure(figsize=(15.5, 9.5), facecolor="white")
    title = (
        config.title.strip()
        or f"Distribuição de {indicator} segundo Regionais de Saúde"
    )
    figure.text(
        0.045,
        0.952,
        textwrap.fill(title, 85),
        fontsize=18 if len(title) > 75 else 21,
        weight="bold",
        color="#172A3A",
    )
    figure.text(
        0.045,
        0.913,
        "Santa Catarina · 17 Regionais de Saúde"
        + (f" · {config.period.strip()}" if config.period.strip() else ""),
        fontsize=12,
        color="#536777",
    )

    map_axis = figure.add_axes([0.035, 0.20, 0.595, 0.66])
    for record in records:
        missing_value = record["value"] is None
        color = "#E5E7EB" if missing_value else colormap(normalizer(record["value"]))
        map_axis.add_patch(
            geometry_patch(
                record["geometry"],
                facecolor=color,
                edgecolor="#F6F8FA",
                linewidth=1.1,
                joinstyle="round",
                hatch="///" if missing_value else None,
            )
        )
    state_geometry = unary_union([record["geometry"] for record in records])
    map_axis.add_patch(
        geometry_patch(
            state_geometry,
            facecolor="none",
            edgecolor="#23313B",
            linewidth=1.25,
        )
    )

    label_offsets = {
        "42005": (16000, -7000),
        "42006": (4000, 11000),
        "42007": (8000, -8000),
        "42011": (10000, 5000),
        "42015": (10000, 3000),
        "42016": (5000, -3000),
        "42017": (18000, -5000),
    }
    for record in records:
        point = max(
            polygons(record["geometry"]), key=lambda item: item.area
        ).representative_point()
        dx, dy = label_offsets.get(record["code"], (0, 0))
        label = map_axis.text(
            point.x + dx,
            point.y + dy,
            str(record["number"]),
            ha="center",
            va="center",
            fontsize=9.2,
            weight="bold",
            color="#0B1820",
            zorder=5,
        )
        label.set_path_effects([effects.withStroke(linewidth=2.5, foreground="white")])

    min_x, min_y, max_x, max_y = state_geometry.bounds
    map_axis.set_xlim(min_x - 25000, max_x + 25000)
    map_axis.set_ylim(min_y - 30000, max_y + 24000)
    map_axis.set_aspect("equal")
    map_axis.axis("off")

    north_x = max_x + 7000
    north_y = max_y - 32000
    map_axis.annotate(
        "N",
        xy=(north_x, north_y + 40000),
        xytext=(north_x, north_y),
        ha="center",
        va="center",
        fontsize=11,
        weight="bold",
        arrowprops={"arrowstyle": "-|>", "lw": 1.4, "color": "#23313B"},
    )
    scale_x = min_x + 24000
    scale_y = min_y + 16000
    map_axis.plot(
        [scale_x, scale_x + 100000], [scale_y, scale_y], color="#23313B", lw=2
    )
    for distance, text in ((0, "0"), (50000, "50"), (100000, "100 km")):
        map_axis.plot(
            [scale_x + distance, scale_x + distance],
            [scale_y - 3500, scale_y + 3500],
            color="#23313B",
            lw=1,
        )
        map_axis.text(
            scale_x + distance,
            scale_y - 9000,
            text,
            ha="center",
            va="top",
            fontsize=7.5,
            color="#394B59",
        )

    table_axis = figure.add_axes([0.655, 0.20, 0.305, 0.66])
    table_axis.axis("off")
    table_axis.text(
        0,
        1.025,
        "Regionais de Saúde",
        fontsize=13,
        weight="bold",
        color="#172A3A",
        transform=table_axis.transAxes,
    )
    table_axis.text(
        1,
        1.025,
        "Valor",
        fontsize=13,
        weight="bold",
        color="#172A3A",
        ha="right",
        transform=table_axis.transAxes,
    )
    rows = [
        [
            str(record["number"]),
            record["name"],
            "Sem dado" if record["value"] is None else format_rate(record["value"]),
        ]
        for record in records
    ]
    table = table_axis.table(
        cellText=rows,
        colLabels=None,
        colWidths=[0.09, 0.69, 0.22],
        cellLoc="left",
        bbox=[0, 0.14, 1, 0.84],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.7)
    for (row, column), cell in table.get_celld().items():
        cell.set_edgecolor("white")
        cell.set_facecolor("#F2F5F7" if row % 2 == 0 else "white")
        cell.PAD = 0.06
        if column == 0:
            cell.set_text_props(weight="bold", color="#172A3A", ha="center")
        elif column == 2:
            cell.set_text_props(weight="bold", color="#172A3A", ha="right")
    table_axis.add_patch(
        mpl.patches.FancyBboxPatch(
            (0, 0.02),
            1,
            0.085,
            boxstyle="round,pad=0.012,rounding_size=0.015",
            facecolor="#E9F0F4",
            edgecolor="none",
            transform=table_axis.transAxes,
        )
    )
    table_axis.text(
        0.035,
        0.062,
        "Santa Catarina",
        fontsize=10.5,
        weight="bold",
        color="#172A3A",
        va="center",
        transform=table_axis.transAxes,
    )
    table_axis.text(
        0.965,
        0.062,
        "Sem dado" if state_value is None else format_rate(state_value),
        fontsize=12,
        weight="bold",
        color="#172A3A",
        ha="right",
        va="center",
        transform=table_axis.transAxes,
    )

    color_axis = figure.add_axes([0.105, 0.12, 0.46, 0.022])
    colorbar = figure.colorbar(
        ScalarMappable(norm=normalizer, cmap=colormap),
        cax=color_axis,
        orientation="horizontal",
    )
    colorbar.set_label(
        indicator + (f" ({config.unit.strip()})" if config.unit.strip() else ""),
        fontsize=9,
        color="#394B59",
        labelpad=5,
    )
    colorbar.ax.tick_params(labelsize=8, colors="#394B59", length=3)
    colorbar.outline.set_edgecolor("#71808A")
    if state_value is not None:
        color_axis.axvline(state_value, color="white", lw=3, zorder=4)
        color_axis.axvline(state_value, color="#172A3A", lw=1.1, zorder=5)
        color_axis.text(
            state_value,
            1.65,
            f"SC {format_rate(state_value)}",
            transform=color_axis.get_xaxis_transform(),
            ha="center",
            va="bottom",
            fontsize=8,
            weight="bold",
            color="#172A3A",
        )
    if any(record["value"] is None for record in records):
        figure.legend(
            handles=[Patch(facecolor="#E5E7EB", edgecolor="#68737D", hatch="///", label="Sem dado")],
            loc="lower center",
            bbox_to_anchor=(0.62, 0.105),
            frameon=False,
            fontsize=8,
        )

    details = (
        f"Arquivo: {source_name}. Fonte: {config.source.strip() or 'não informada'}. "
        f"Autores: {config.authors.strip() or 'não informados'}. "
        f"Gerado em: {datetime.now().astimezone().strftime('%d/%m/%Y %H:%M')}. "
        f"Unidade: {config.unit.strip() or 'não informada'}. "
        f"Período: {config.period.strip() or 'não informado'}."
    )
    method = (
        "Método: valores associados às Regionais de Saúde informadas, sem estimativa municipal. "
        "Regionais ausentes ou com célula vazia são mostradas como Sem dado; zero é preservado. "
        "Geografia: municípios do IBGE agrupados pela composição de Regiões de Saúde do Ministério da Saúde; "
        "projeção EPSG:5880. Gerador de Relatórios SC v0.1.0 "
        f"({config.processing_context})."
    )
    figure.text(
        0.045,
        0.018,
        textwrap.fill(details, 190) + "\n" + textwrap.fill(method, 190),
        fontsize=6.9,
        color="#5B6B77",
        linespacing=1.22,
    )

    pdf_output.parent.mkdir(parents=True, exist_ok=True)
    png_output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        pdf_output,
        facecolor="white",
        bbox_inches="tight",
        metadata={
            "Title": title,
            "Author": config.authors,
            "Subject": "Mapa das 17 Regionais de Saude de Santa Catarina",
            "Creator": (
                "Gerador de Relatorios SC v0.1.0 "
                f"{config.processing_context}, Python, Matplotlib"
            ),
        },
    )
    figure.savefig(png_output, dpi=200, facecolor="white", bbox_inches="tight")
    plt.close(figure)


def render_regional_report(
    source: str | Path, pdf_output: Path, png_output: Path, config: RegionalConfig
) -> None:
    values, state_value, indicator, _ = read_values(source)
    metadata, municipalities = read_region_mapping()
    geometries = build_geometries(municipalities)
    draw_figure(
        metadata,
        geometries,
        values,
        state_value,
        indicator,
        config,
        Path(source).name,
        pdf_output,
        png_output,
    )
