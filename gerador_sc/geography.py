"""Recursos geograficos locais para os mapas de Santa Catarina."""

from __future__ import annotations

import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform


MAP_CODES = (
    "4213",
    "4217",
    "4218",
    "4210",
    "4211",
    "4214",
    "4215",
    "4216",
)
MAP_NAMES = {
    "4213": "Grande Oeste",
    "4217": "Meio Oeste",
    "4218": "Serra Catarinense",
    "4210": "Sul",
    "4211": "Planalto Norte e Nordeste",
    "4214": "Grande Florianopolis",
    "4215": "Foz do Rio Itajai",
    "4216": "Vale do Itajai",
}
MAP_COLORS = ("#D95F59", "#D6B258", "#B7D77A", "#4E9F63")
MAP_BANDS = (
    "Menor que 45%",
    "45% a menos de 70%",
    "70% a menos de 95%",
    "95% ou mais",
)


def resource_directory() -> Path:
    return Path(__file__).resolve().parent.parent / "geodados"


def load_projected_geometries() -> dict[str, object]:
    path = resource_directory() / "sc_macrorregioes_saude.geojson"
    if not path.exists():
        raise FileNotFoundError("Recurso geografico ausente: geodados/sc_macrorregioes_saude.geojson")
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = {str(feature["properties"]["codigo"]): shape(feature["geometry"]) for feature in payload["features"]}
    if set(features) != set(MAP_CODES):
        raise ValueError("O recurso geografico nao contem exatamente as oito macrorregioes esperadas.")
    if any(geometry.is_empty or not geometry.is_valid for geometry in features.values()):
        raise ValueError("O recurso geografico contem uma geometria vazia ou invalida.")
    projector = Transformer.from_crs("EPSG:4674", "EPSG:5880", always_xy=True)
    return {code: transform(projector.transform, geometry) for code, geometry in features.items()}


def band(value: float | None) -> int | None:
    if value is None:
        return None
    return 0 if value < 45 else 1 if value < 70 else 2 if value < 95 else 3
