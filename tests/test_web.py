from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import openpyxl
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from gerador_sc import regional as regional_module
from gerador_sc.importers import inspect_file
from gerador_sc.regional import RegionalConfig, read_values
from webapp import api as api_module
from webapp.api import create_app

ROOT = Path(__file__).resolve().parents[1]
ANNUAL = ROOT / "data" / "exemplos" / "BANCO DE DADOS CV - AMANDA E EMILENE.xlsx"
REGIONAL = ROOT / "data" / "exemplos" / "taxa estado SC.xlsx"
REGIONAL_FIXTURE = ROOT / "tests" / "fixtures" / "regionais_sc_parcial_FICTICIA.csv"


def assessment_workbook() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Avaliações"
    sheet.append(["Pesquisa sem dados pessoais"])
    sheet.append(["Questão", "% Erro", "Erros", "Avaliação", "Acertos", "% Acerto"])
    sheet.append([1, 0.25, 1, "1ª avaliação", 3, 0.75])
    sheet.append([2, 0.0, 0, "1ª avaliação", 4, 1.0])
    sheet.append([None, 0.125, 1, "TOTAL 1ª avaliação", 7, 0.875])
    sheet.append([1, "8,33%%", 1, "2ª avaliação", 11, 0.9167])
    sheet.append([2, 0.0, 0, "2ª avaliação", 12, 1.0])
    sheet.append([None, "4,17%", 1, "TOTAL 2ª avaliação", 23, 0.9583])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_assessment_inspection_and_pdf_keep_evaluations_separate() -> None:
    web = client()
    content = assessment_workbook()
    inspected = web.post("/api/inspect", files={"file": ("avaliacoes.xlsx", content)})
    assert inspected.status_code == 200
    data = inspected.json()
    assert data["kind"] == "assessment"
    assert [item["question_count"] for item in data["evaluations"]] == [2, 2]
    assert [item["response_counts"] for item in data["evaluations"]] == [[4], [12]]
    assert data["evaluations"][0]["rate"] == 87.5
    assert data["evaluations"][1]["rate"] == 95.83
    assert any("Linha 6" in warning for warning in data["warnings"])
    generated = web.post(
        "/api/generate",
        files={"file": ("avaliacoes.xlsx", content)},
        data={"options": json.dumps({"kind": "assessment", "model": "avaliacao_questoes", "title": "Pesquisa", "authors": "Equipe", "source": "Pesquisa interna"})},
    )
    assert generated.status_code == 200
    assert generated.headers["content-type"] == "application/pdf"
    assert len(PdfReader(io.BytesIO(generated.content)).pages) == 4


def test_assessment_rejects_invalid_question_count() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Avaliação", "Questão", "Acertos", "Erros"])
    sheet.append(["1ª avaliação", 1, 3, -1])
    output = io.BytesIO()
    workbook.save(output)
    response = client().post("/api/inspect", files={"file": ("erro.xlsx", output.getvalue())})
    assert response.status_code == 422
    assert "inteiro não negativo" in response.json()["detail"]


def test_assessment_accepts_tcc_shape_and_total_in_question_column() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Avaliação", "Questão", "Acertos", "Erros", "% Acerto", "% Erro"])
    for number in range(1, 16):
        sheet.append(["1ª avaliação", number, 17, 1, None, None])
    sheet.append(["1ª avaliação", "TOTAL", 255, 15, None, None])
    for number in range(1, 15):
        sheet.append(["2ª avaliação", number, 11, 1, None, None])
    sheet.append(["2ª avaliação", "TOTAL", 154, 14, None, "8,33%%"])
    output = io.BytesIO()
    workbook.save(output)
    response = client().post("/api/inspect", files={"file": ("tcc.xlsx", output.getvalue())})
    assert response.status_code == 200
    data = response.json()
    assert [item["question_count"] for item in data["evaluations"]] == [15, 14]
    assert [item["response_counts"] for item in data["evaluations"]] == [[18], [12]]
    assert [item["correct"] for item in data["evaluations"]] == [255, 154]
    assert any("Linha 32" in warning for warning in data["warnings"])


def test_single_assessment_does_not_claim_different_questions() -> None:
    content = "Avaliação;Questão;Acertos;Erros\nÚnica;1;4;1\n"
    response = client().post("/api/inspect", files={"file": ("unica.csv", content.encode())})
    assert response.status_code == 200
    assert response.json()["warnings"] == []


@pytest.fixture(autouse=True)
def reset_test_rate_limits() -> None:
    api_module._rate_events.clear()


def client() -> TestClient:
    return TestClient(create_app())


def invoke_asgi_without_content_length(app, body: bytes) -> list[dict[str, object]]:
    async def run_request() -> list[dict[str, object]]:
        sent: list[dict[str, object]] = []
        cursor = 0
        chunk_size = 512 * 1024

        async def receive() -> dict[str, object]:
            nonlocal cursor
            if cursor < len(body):
                chunk = body[cursor : cursor + chunk_size]
                cursor += len(chunk)
                return {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": cursor < len(body),
                }
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/inspect",
            "raw_path": b"/api/inspect",
            "query_string": b"",
            "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "state": {},
        }
        await app(scope, receive, send)
        return sent

    return asyncio.run(run_request())


def test_public_api_accepts_upload_without_session() -> None:
    web = client()
    response = web.post("/api/inspect", files={"file": ("dados.csv", b"a;b\n1;2")})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == "Formato de planilha não reconhecido para geração automática."
    assert "tabela anual" not in str(detail).lower()
    assert web.get("/api/session").status_code == 404


def test_recognized_annual_table_with_invalid_values_has_distinct_message() -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Região", 2023, 2024, 2025])
    sheet.append(["4210 Região", 1, "valor inválido", 3])
    output = io.BytesIO()
    workbook.save(output)
    response = client().post("/api/inspect", files={"file": ("anual.xlsx", output.getvalue())})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == "Há tabelas com problemas que impedem a geração."
    assert any(item["code"] == "INVALID_VALUE" for item in detail["diagnostics"])


def test_request_body_limit_rejects_large_content_length_before_multipart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_temporary_directory(*args, **kwargs):
        raise AssertionError("A solicitação excedente não deve criar temporários.")

    monkeypatch.setattr(
        api_module.tempfile, "TemporaryDirectory", unexpected_temporary_directory
    )
    oversized = b"x" * (api_module.MAX_REQUEST_BODY_BYTES + 1)
    response = client().post(
        "/api/inspect",
        content=oversized,
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )

    assert response.status_code == 413
    assert "corpo" in response.json()["detail"].lower()
    assert response.headers["cache-control"] == "no-store"


def test_request_body_limit_counts_streamed_bytes_without_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_temporary_directory(*args, **kwargs):
        raise AssertionError("A solicitação excedente não deve criar temporários.")

    monkeypatch.setattr(
        api_module.tempfile, "TemporaryDirectory", unexpected_temporary_directory
    )
    app = create_app()
    body = b"x" * (api_module.MAX_REQUEST_BODY_BYTES + 1)
    sent = invoke_asgi_without_content_length(app, body)
    start = next(message for message in sent if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )

    assert start["status"] == 413
    assert b"corpo" in response_body.lower()


def test_file_limit_stays_separate_and_temporary_upload_is_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_temporary_directory = api_module.tempfile.TemporaryDirectory
    temporary_paths: list[Path] = []

    class TrackedTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            self.directory = original_temporary_directory(*args, **kwargs)

        def __enter__(self):
            path = Path(self.directory.__enter__())
            temporary_paths.append(path)
            return path

        def __exit__(self, *args):
            return self.directory.__exit__(*args)

    monkeypatch.setattr(
        api_module.tempfile, "TemporaryDirectory", TrackedTemporaryDirectory
    )
    oversized_file = b"x" * (api_module.MAX_UPLOAD_BYTES + 1)
    response = client().post(
        "/api/inspect",
        files={"file": ("grande.csv", oversized_file, "text/csv")},
    )

    assert response.status_code == 413
    assert "planilha" in response.json()["detail"].lower()
    assert temporary_paths
    assert all(not path.exists() for path in temporary_paths)


def test_expanded_xlsx_limit_stays_separate_and_temporary_is_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_temporary_directory = api_module.tempfile.TemporaryDirectory
    temporary_paths: list[Path] = []

    class TrackedTemporaryDirectory:
        def __init__(self, *args, **kwargs):
            self.directory = original_temporary_directory(*args, **kwargs)

        def __enter__(self):
            path = Path(self.directory.__enter__())
            temporary_paths.append(path)
            return path

        def __exit__(self, *args):
            return self.directory.__exit__(*args)

    monkeypatch.setattr(
        api_module.tempfile, "TemporaryDirectory", TrackedTemporaryDirectory
    )
    workbook = io.BytesIO()
    with ZipFile(workbook, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("xl/workbook.xml", b"<workbook/>")
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            b"0" * (api_module.MAX_UNPACKED_BYTES + 1),
        )
    payload = workbook.getvalue()
    assert len(payload) < api_module.MAX_REQUEST_BODY_BYTES

    response = client().post(
        "/api/inspect",
        files={"file": ("expandida.xlsx", payload)},
    )

    assert response.status_code == 413
    assert "expandida" in response.json()["detail"].lower()
    assert temporary_paths
    assert all(not path.exists() for path in temporary_paths)


def test_regional_api_requests_only_the_selected_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_formats: list[str] = []

    def fake_render(source, pdf_path, png_path, config, *, output_format):
        requested_formats.append(output_format)
        if output_format == "pdf":
            pdf_path.write_bytes(b"PDF ficticio")
        elif output_format == "png":
            png_path.write_bytes(b"\x89PNG ficticio")

    monkeypatch.setattr(api_module, "render_regional_report", fake_render)
    web = client()

    for output_format, expected_type, expected_content in (
        ("pdf", "application/pdf", b"PDF ficticio"),
        ("png", "image/png", b"\x89PNG ficticio"),
    ):
        options = {
            "kind": "regional",
            "title": "Mapa fictício",
            "format": output_format,
        }
        response = web.post(
            "/api/generate",
            files={"file": (REGIONAL_FIXTURE.name, REGIONAL_FIXTURE.read_bytes())},
            data={"options": json.dumps(options)},
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith(expected_type)
        assert response.content == expected_content

    assert requested_formats == ["pdf", "png"]


@pytest.mark.parametrize(
    ("output_format", "expected_paths"),
    [
        ("pdf", ("pdf", None)),
        ("png", (None, "png")),
        ("both", ("pdf", "png")),
    ],
)
def test_regional_motor_selects_only_requested_outputs_and_default_keeps_both(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    output_format: str,
    expected_paths: tuple[str | None, str | None],
) -> None:
    original_read_mapping = regional_module.read_region_mapping
    mapping_calls = 0
    requested_paths: list[tuple[str | None, str | None]] = []

    def tracked_read_mapping():
        nonlocal mapping_calls
        mapping_calls += 1
        return original_read_mapping()

    def record_draw(*args):
        pdf_path, png_path = args[-2:]
        requested_paths.append(
            (
                pdf_path.suffix[1:] if pdf_path is not None else None,
                png_path.suffix[1:] if png_path is not None else None,
            )
        )

    monkeypatch.setattr(regional_module, "read_region_mapping", tracked_read_mapping)
    monkeypatch.setattr(regional_module, "build_geometries", lambda municipalities: {})
    monkeypatch.setattr(regional_module, "draw_figure", record_draw)
    arguments = (
        REGIONAL_FIXTURE,
        tmp_path / "relatorio.pdf",
        tmp_path / "relatorio.png",
        RegionalConfig("Relatório fictício"),
    )

    if output_format == "both":
        regional_module.render_regional_report(*arguments)
    else:
        regional_module.render_regional_report(
            *arguments, output_format=output_format
        )

    assert requested_paths == [expected_paths]
    assert mapping_calls == 1


@pytest.mark.parametrize("variation,annual_count", [(1, 3), (2, 3), (3, 1), (4, 3), (5, 1)])
def test_five_fictional_layouts_generate_annual_and_regional_bar_pdfs(variation: int, annual_count: int) -> None:
    path = ROOT / "tests" / "fixtures" / f"dados_ficticios_variacao_{variation:02d}.xlsx"
    original = path.read_bytes()
    files = {"file": (path.name, original)}
    web = client()
    inspection = web.post("/api/inspect", files=files)
    assert inspection.status_code == 200, inspection.text
    data = inspection.json()
    annual = [table for table in data["import"]["tabelas"] if table["valida"]]
    categorical = data["import"]["tabelas_categoricas"]
    assert len(annual) == annual_count
    assert len(categorical) == 1
    assert all(table["anos"] == list(range(2016, 2026)) for table in annual)
    assert all(not table["mapa_disponivel"] for table in annual)
    assert len(categorical[0]["categorias"]) == 8

    options = {"kind": "annual", "title": "Comparação das regiões", "authors": "Equipe", "source": "Planilha fictícia", "table_ids": [annual[0]["id"]], "years": [2025], "model": "barras", "confirmed_exclusions": []}
    pdf = web.post("/api/generate", files=files, data={"options": json.dumps(options)})
    assert pdf.status_code == 200, pdf.text
    assert len(PdfReader(io.BytesIO(pdf.content)).pages) == 2
    options = {"kind": "annual", "title": "Taxa por regional", "authors": "Equipe", "source": "Planilha fictícia", "unit": "taxa", "period": "2025", "model": "barras_categoria", "category_id": categorical[0]["id"]}
    pdf = web.post("/api/generate", files=files, data={"options": json.dumps(options)})
    assert pdf.status_code == 200, pdf.text
    pages = PdfReader(io.BytesIO(pdf.content)).pages
    assert len(pages) == 2
    assert "2025" in pages[-1].extract_text()
    assert path.read_bytes() == original


def test_pie_rejects_rates_and_preserves_zero_and_over_100() -> None:
    path = ROOT / "tests" / "fixtures" / "dados_ficticios_variacao_01.xlsx"
    web = client()
    files = {"file": (path.name, path.read_bytes())}
    table = web.post("/api/inspect", files=files).json()["import"]["tabelas"][0]
    options = {"kind": "annual", "title": "Tentativa", "table_ids": [table["id"]], "years": [2025], "model": "pizza", "confirmed_exclusions": []}
    response = web.post("/api/generate", files=files, data={"options": json.dumps(options)})
    assert response.status_code == 422
    assert any(item["code"] == "PIE_REQUIRES_COUNTS" for item in response.json()["detail"]["diagnostics"])
    assert any(value is not None and value > 100 for series in table["series"] for value in series["valores"])


def test_pie_generates_for_regional_birth_counts() -> None:
    web = client()
    files = {"file": (ANNUAL.name, ANNUAL.read_bytes())}
    tables = web.post("/api/inspect", files=files).json()["import"]["tabelas"]
    table = next(item for item in tables if item["aba"] == "NASCIDOS VIVOS SC")
    options = {"kind": "annual", "title": "Nascidos vivos por região", "table_ids": [table["id"]], "years": [2025], "model": "pizza", "confirmed_exclusions": []}
    response = web.post("/api/generate", files=files, data={"options": json.dumps(options)})
    assert response.status_code == 200, response.text
    assert len(PdfReader(io.BytesIO(response.content)).pages) == 2


def test_scrambled_years_keep_original_cell_values_and_unknown_unit() -> None:
    path = ROOT / "tests" / "fixtures" / "dados_ficticios_variacao_05.xlsx"
    result = inspect_file(path)
    table = result.valid_tables[0]
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        first_original = workbook.active.cell(6, 4).value
        label_original = workbook.active.cell(6, 5).value
    finally:
        workbook.close()
    assert table.series[0].name == label_original
    assert table.series[0].values[table.years.index(2025)] == first_original
    assert table.indicator_type == "desconhecido"
    assert table.unit == "Valor informado na planilha"


def test_regional_workbook_generates_pdf_and_png_without_changing_source() -> None:
    web = client()
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


def test_annual_workbook_generates_web_pdf() -> None:
    web = client()
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


def test_mismatched_model_is_rejected() -> None:
    web = client()
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


def test_regional_csv_accepts_partial_data_and_marks_missing_regions() -> None:
    web = client()
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
    partial_data = (ROOT / "tests" / "fixtures" / "regionais_sc_parcial_FICTICIA.csv").read_bytes()
    partial = web.post(
        "/api/inspect",
        files={"file": ("regionais.csv", partial_data)},
    )
    assert partial.status_code == 200, partial.text
    data = partial.json()
    assert data["data_region_count"] == 2
    assert data["missing_region_count"] == 15
    assert data["state_value"] is None
    assert data["regions"][0]["value"] == 0
    assert data["regions"][1]["value"] == 30
    assert any(item["in_file"] and item["value"] is None for item in data["regions"])
    assert any(not item["in_file"] and item["value"] is None for item in data["regions"])

    options = {"kind": "regional", "title": "Mapa parcial", "unit": "taxa", "format": "pdf"}
    pdf = web.post("/api/generate", files={"file": ("regionais.csv", partial_data)}, data={"options": json.dumps(options)})
    assert pdf.status_code == 200, pdf.text
    page = PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text()
    assert "Sem dado" in page
    assert "zero é preservado" in page
    options["format"] = "png"
    png = web.post("/api/generate", files={"file": ("regionais.csv", partial_data)}, data={"options": json.dumps(options)})
    assert png.status_code == 200, png.text
    assert png.content.startswith(b"\x89PNG")

    for bad_data, detail in [
        ("Regionais;Taxa\nNOME DESCONHECIDO;1", "sem correspondencia geografica"),
        ("Regionais;Taxa\nEXTREMO OESTE;", "Nenhuma Regional"),
    ]:
        response = web.post("/api/inspect", files={"file": ("regionais.csv", bad_data.encode())})
        assert response.status_code == 422
        assert detail in response.json()["detail"]


def test_generic_macro_map_is_available_through_web() -> None:
    path = ROOT / "tests" / "fixtures" / "taxa_sc_macrorregioes_FICTICIA.csv"
    files = {"file": (path.name, path.read_bytes())}
    web = client()
    inspected = web.post("/api/inspect", files=files)
    assert inspected.status_code == 200, inspected.text
    table = next(item for item in inspected.json()["import"]["tabelas"] if item["valida"])
    assert table["mapa_disponivel"]
    assert table["tipo_indicador"] == "desconhecido"

    options = {"kind": "annual", "title": "Taxa por macrorregião", "table_ids": [table["id"]], "years": [2020, 2021], "model": "mapa", "confirmed_exclusions": []}
    pdf = web.post("/api/generate", files=files, data={"options": json.dumps(options)})
    assert pdf.status_code == 200, pdf.text
    pages = PdfReader(io.BytesIO(pdf.content)).pages
    assert len(pages) == 3
    assert "Sem dado" in pages[0].extract_text()
    assert "escala linear comum" in pages[-1].extract_text()


def test_invalid_spreadsheets_have_readable_errors() -> None:
    web = client()
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
