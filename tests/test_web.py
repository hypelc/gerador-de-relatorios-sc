from __future__ import annotations

import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader

from gerador_sc.regional import read_values
from webapp.api import create_app

ROOT = Path(__file__).resolve().parents[1]
ANNUAL = ROOT / "data" / "exemplos" / "BANCO DE DADOS CV - AMANDA E EMILENE.xlsx"
REGIONAL = ROOT / "data" / "exemplos" / "taxa estado SC.xlsx"


def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_ACCESS_PASSWORD", "senha-para-o-teste-123")
    monkeypatch.setenv("APP_SESSION_SECRET", "0123456789abcdef0123456789abcdef")
    return TestClient(create_app())


def authenticate(web: TestClient) -> None:
    response = web.post("/api/login", json={"password": "senha-para-o-teste-123"})
    assert response.status_code == 200


def test_private_api_requires_login(monkeypatch) -> None:
    web = client(monkeypatch)
    response = web.post("/api/inspect", files={"file": ("dados.csv", b"a;b\n1;2")})
    assert response.status_code == 401
    assert web.get("/api/session").json() == {"authenticated": False}
    authenticate(web)
    assert web.get("/api/session").json() == {"authenticated": True}


def test_regional_workbook_generates_pdf_and_png_without_changing_source(
    monkeypatch,
) -> None:
    web = client(monkeypatch)
    authenticate(web)
    source = REGIONAL.read_bytes()
    files = {"file": (REGIONAL.name, source)}
    inspected = web.post("/api/inspect", files=files)
    assert inspected.status_code == 200
    data = inspected.json()
    assert data["kind"] == "regional"
    assert len(data["regions"]) == 17
    options = {
        "kind": "regional",
        "title": "Distribuição da taxa de profissionais",
        "authors": "Equipe de pesquisa",
        "source": "Planilha fornecida",
        "period": "2025",
        "unit": "por 1.000 habitantes",
        "format": "pdf",
    }
    pdf = web.post("/api/generate", files=files, data={"options": json.dumps(options)})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    text = "\n".join(
        page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages
    )
    assert "Equipe de pesquisa" in text
    assert "2025" in text
    assert "sem estimativa municipal" in text
    options["format"] = "png"
    png = web.post("/api/generate", files=files, data={"options": json.dumps(options)})
    assert png.status_code == 200
    assert png.content.startswith(b"\x89PNG")
    assert REGIONAL.read_bytes() == source


def test_annual_workbook_generates_web_pdf(monkeypatch) -> None:
    web = client(monkeypatch)
    authenticate(web)
    files = {"file": (ANNUAL.name, ANNUAL.read_bytes())}
    inspected = web.post("/api/inspect", files=files)
    assert inspected.status_code == 200
    data = inspected.json()
    assert data["kind"] == "annual"
    assert len(data["import"]["tabelas"]) == 22
    table = next(table for table in data["import"]["tabelas"] if table["valida"])
    options = {
        "kind": "annual",
        "title": "Evolução da cobertura",
        "authors": "Equipe",
        "source": "Planilha da pesquisa",
        "unit": "",
        "table_ids": [table["id"]],
        "years": table["anos"],
        "model": "paineis",
        "confirmed_exclusions": [],
    }
    pdf = web.post("/api/generate", files=files, data={"options": json.dumps(options)})
    assert pdf.status_code == 200
    pages = PdfReader(io.BytesIO(pdf.content)).pages
    assert len(pages) == 2
    method = pages[-1].extract_text()
    assert "Processamento no servidor" in method
    assert "Processamento local" not in method


def test_mismatched_model_is_rejected(monkeypatch) -> None:
    web = client(monkeypatch)
    authenticate(web)
    options = {
        "kind": "annual",
        "title": "Erro",
        "table_ids": [],
        "years": [],
        "model": "paineis",
    }
    response = web.post(
        "/api/generate",
        files={"file": (REGIONAL.name, REGIONAL.read_bytes())},
        data={"options": json.dumps(options)},
    )
    assert response.status_code == 422


def test_regional_csv_is_recognized_and_missing_region_is_explained(
    monkeypatch,
) -> None:
    web = client(monkeypatch)
    authenticate(web)
    regions, state, _, _ = read_values(REGIONAL)
    rows = [
        "Regionais;Taxa de profissionais",
        *(f"{name};{value}" for name, value in regions.values()),
        f"Santa Catarina;{state}",
    ]
    csv_data = "\n".join(rows).encode("utf-8")
    recognized = web.post("/api/inspect", files={"file": ("regionais.csv", csv_data)})
    assert recognized.status_code == 200
    assert recognized.json()["kind"] == "regional"
    assert len(recognized.json()["regions"]) == 17
    missing = web.post(
        "/api/inspect",
        files={"file": ("regionais.csv", "\n".join(rows[:2] + rows[-1:]).encode())},
    )
    assert missing.status_code == 422
    assert "Faltam Regionais" in missing.json()["detail"]


def test_invalid_spreadsheets_have_readable_errors(monkeypatch) -> None:
    web = client(monkeypatch)
    authenticate(web)
    malformed_csv = web.post(
        "/api/inspect", files={"file": ("dados.csv", b"Regionais;Taxa\n\xff;1")}
    )
    assert malformed_csv.status_code == 422
    assert "CSV" in malformed_csv.json()["detail"]

    fake_xlsx = web.post(
        "/api/inspect", files={"file": ("dados.xlsx", b"not an Excel workbook")}
    )
    assert fake_xlsx.status_code == 400
    assert "danificado" in fake_xlsx.json()["detail"]
