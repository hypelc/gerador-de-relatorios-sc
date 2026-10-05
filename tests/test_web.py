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


def multi_sheet_assessment_workbook(
    *,
    base_rows: list[tuple[object, ...]] | None = None,
    summary_rows: list[tuple[object, ...]] | None = None,
    additional_base_sheets: list[tuple[str, list[tuple[object, ...]]]] | None = None,
    include_invalid_auxiliary: bool = False,
    header_offset: int = 0,
    summary_headers: tuple[object, ...] = ("Avaliação", "Acertos", "Erros", "Percentual"),
) -> bytes:
    base_rows = base_rows or [
        (101, "A", 1, 21, 3),
        (102, "A", 2, 24, 0),
        (103, "A", 3, 20, 4),
        (104, "A", 4, 18, 6),
        (105, "A", 5, 23, 1),
        (106, "A", 6, 19, 5),
        (107, "A", 7, 22, 2),
        (None, None, None, None, None),
        (201, "B", 1, 13, 2),
        (202, "B", 2, 15, 0),
        (203, "B", 3, 12, 3),
        (204, "B", 4, 14, 1),
        (205, "B", 5, 9, 6),
        (206, "B", 6, 15, 0),
        (207, "B", 7, 11, 4),
        (208, "B", 8, 14, 1),
    ]
    summary_rows = summary_rows or [
        ("Prova A", 147, 21, 0.875),
        ("Prova B", 103, 17, 0.8583333333333333),
    ]
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    if include_invalid_auxiliary:
        auxiliary = workbook.create_sheet("Auxiliar")
        auxiliary.append(["Questão", "Acertos", "Erros"])
        auxiliary.append(["não é uma questão", "inválido", 0])

    def add_base_sheet(name: str, rows: list[tuple[object, ...]], offset: int = 0) -> None:
        sheet = workbook.create_sheet(name)
        for row_index in range(offset):
            sheet.append(["Dados da avaliação"] if row_index == 0 else [])
        sheet.append(["ID", "Prova", "Pergunta", "Corretas", "Incorretas"])
        for row in rows:
            sheet.append(row)

    add_base_sheet("Base", base_rows, header_offset)
    for name, rows in additional_base_sheets or []:
        add_base_sheet(name, rows)

    summary = workbook.create_sheet("Resumo")
    summary.append(["Resumo geral das provas"])
    summary.append(summary_headers)
    for row in summary_rows:
        summary.append(row)
    summary.append(["Observação", "Valor", "Tipo"])
    summary.append(["Meta", "85%", "texto"])
    summary.append(["Limite mínimo", 0.7, "decimal"])
    summary.append(["Participantes", 24, "número"])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def traditional_assessment_workbook(
    *,
    response_mismatch_question: int | None = None,
    duplicate_question: bool = False,
    zero_denominator_question: int | None = None,
    divergent_total: bool = False,
    include_response_count: bool = True,
) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Avaliacoes"
    sheet.append(["Avaliação diagnóstica"])
    sheet.append([])
    headers = ["Questão", "Acertos", "Erros", "% Acerto", "% Erro"]
    if include_response_count:
        headers.insert(1, "Respostas")
    sheet.append(headers)
    correct_counts = [20, 19, 19, *([17] * 9)]
    for question_number, correct in enumerate(correct_counts, start=1):
        number = 1 if duplicate_question and question_number == 2 else question_number
        incorrect = 20 - correct
        responses = 20
        if question_number == response_mismatch_question:
            responses -= 1
        if question_number == zero_denominator_question:
            correct, incorrect, responses = 0, 0, 0
        row_number = sheet.max_row + 1
        correct_column = 3 if include_response_count else 2
        incorrect_column = correct_column + 1
        denominator = f"{chr(64 + correct_column)}{row_number}+{chr(64 + incorrect_column)}{row_number}"
        values = [
            number,
            correct,
            incorrect,
            f"={chr(64 + correct_column)}{row_number}/({denominator})",
            f"={chr(64 + incorrect_column)}{row_number}/({denominator})",
        ]
        if include_response_count:
            values.insert(1, responses)
        sheet.append(values)
        sheet.cell(row_number, correct_column + 2).number_format = "0.00%"
        sheet.cell(row_number, correct_column + 3).number_format = "0.00%"
    total_correct, total_incorrect = (212, 28) if divergent_total else (211, 29)
    total_values = ["TOTAL", total_correct, total_incorrect, None, None]
    if include_response_count:
        total_values.insert(1, 240)
    sheet.append(total_values)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def assessment_workbook_with_sheets(
    sheets: list[tuple[str, bytes]],
) -> bytes:
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, content in sheets:
        source_workbook = openpyxl.load_workbook(io.BytesIO(content))
        target_sheet = workbook.create_sheet(title)
        for row in source_workbook.active.iter_rows(values_only=True):
            target_sheet.append(row)
        source_workbook.close()
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def assessment_workbook_with_candidate_blocks(
    blocks: list[list[list[object]]],
) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Comparativo"
    for block in blocks:
        for row in block:
            sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def side_by_side_assessment_workbook(
    *,
    left_questions: list[tuple[object, ...]] | None = None,
    right_questions: list[tuple[object, ...]] | None = None,
    left_summary: tuple[object, ...] = ("Resumo", 21, 139, 160),
    right_summary: tuple[object, ...] = ("TOTAL", 108, 95, 13),
    summary_rates: tuple[object, object] = (0.86875, 0.8796296296296297),
    right_header: tuple[object, ...] = ("ITEM", "TOTAL", "ACERTOS", "ERROS"),
    separator_column: bool = True,
    separator_value: object | None = None,
) -> bytes:
    if left_questions is None:
        left_questions = [
            ("Q1", 2, 14, 16),
            ("Q2", 1, 15, 16),
            ("Q3", 3, 13, 16),
            ("Q4", 0, 16, 16),
            ("Q5", 4, 12, 16),
            ("Q6", 1, 15, 16),
            ("Q7", 5, 11, 16),
            ("Q8", 0, 16, 16),
            ("Q9", 2, 14, 16),
            ("Q10", 3, 13, 16),
        ]
    if right_questions is None:
        right_questions = [
            ("Questão 1", 12, 10, 2),
            ("Questão 2", 12, 12, 0),
            ("Questão 3", 12, 11, 1),
            ("Questão 4", 12, 9, 3),
            ("Questão 5", 12, 12, 0),
            ("Questão 6", 12, 8, 4),
            ("Questão 7", 12, 11, 1),
            ("Questão 8", 12, 12, 0),
            ("Questão 9", 12, 10, 2),
        ]
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Comparativo"
    sheet.append([])
    sheet.append([None, "DADOS FICTÍCIOS — COMPARATIVO"])
    sheet.append([])
    header = [None, "ITEM", "ERROS", "ACERTOS", "TOTAL"]
    if separator_column:
        header.append(None)
    sheet.append([*header, *right_header])

    def append_blocks(
        left: tuple[object, ...] = (),
        right: tuple[object, ...] = (),
        separator: object | None = None,
    ) -> None:
        sheet.append(
            [None, *(left or (None,) * 4), separator, *(right or (None,) * 4)]
        )

    for index in range(max(len(left_questions), len(right_questions))):
        left = left_questions[index] if index < len(left_questions) else ()
        right = right_questions[index] if index < len(right_questions) else ()
        append_blocks(left, right, separator_value if index == 0 else None)
    append_blocks()
    append_blocks((), right_summary)
    append_blocks(left_summary)
    append_blocks(("Indicador", "Valor"))
    append_blocks(("Taxa de acerto A", summary_rates[0]))
    append_blocks(("Taxa de acerto B", summary_rates[1]))
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def invalid_assessment_candidate_workbook() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Questão", "Acertos", "Erros"])
    sheet.append(["não é uma questão", "inválido", 0])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def invalid_assessment_candidate_with_multiple_headers_workbook() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    headers = ["Questão", "Acertos", "Erros"]
    sheet.append(headers)
    sheet.append(["não é uma questão", "inválido", 0])
    sheet.append(headers)
    sheet.append(["também não é uma questão", "inválido", 0])
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


def test_multisheet_assessment_uses_base_and_checks_summary_in_pdf() -> None:
    web = client()
    content = multi_sheet_assessment_workbook(header_offset=2)

    inspected = web.post("/api/inspect", files={"file": ("multiplas_provas.xlsx", content)})

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    assert data["kind"] == "assessment"
    assert data["sheet"] == "Base"
    assert [item["name"] for item in data["evaluations"]] == ["Prova A", "Prova B"]
    assert [item["question_count"] for item in data["evaluations"]] == [7, 8]
    assert [item["response_counts"] for item in data["evaluations"]] == [[24], [15]]
    assert [(item["correct"], item["incorrect"], item["rate"]) for item in data["evaluations"]] == [
        (147, 21, 87.5),
        (103, 17, 85.83),
    ]
    assert data["evaluations"][0]["questions"][0]["number"] == 1
    assert data["evaluations"][0]["questions"][0]["number"] != 101
    assert data["evaluations"][0]["questions"][1]["incorrect"] == 0
    assert data["evaluations"][1]["questions"][-1]["number"] == 8
    assert all(item["name"] != "Resumo" for item in data["evaluations"])

    generated = web.post(
        "/api/generate",
        files={"file": ("multiplas_provas.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resultados por prova",
                }
            )
        },
    )

    assert generated.status_code == 200, generated.text
    pages = PdfReader(io.BytesIO(generated.content)).pages
    pdf_text = "\n".join(page.extract_text() or "" for page in pages)
    assert "Prova A" in pdf_text
    assert "Prova B" in pdf_text
    assert "87,50%" in pdf_text
    assert "85,83%" in pdf_text
    assert "147 acertos" in pdf_text and "21 erros" in pdf_text
    assert "103 acertos" in pdf_text and "17 erros" in pdf_text
    assert "15 respostas por questão" in pdf_text
    assert "Participantes" not in pdf_text


def test_multisheet_summary_divergence_warns_but_base_remains_authoritative() -> None:
    content = multi_sheet_assessment_workbook(
        summary_rows=[("Prova A", 147, 21, 0.875), ("Prova B", 104, 16, 0.8667)]
    )
    web = client()

    inspected = web.post(
        "/api/inspect", files={"file": ("resumo_divergente.xlsx", content)}
    )

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    prova_b = data["evaluations"][1]
    assert (prova_b["correct"], prova_b["incorrect"], prova_b["rate"]) == (103, 17, 85.83)
    warning = " ".join(data["warnings"])
    assert "Resumo" in warning
    assert "104 acertos e 16 erros" in warning
    assert "103 acertos e 17 erros" in warning
    assert "dados detalhados da Base" in warning

    generated = web.post(
        "/api/generate",
        files={"file": ("resumo_divergente.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resumo conferido",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(generated.content)).pages
    )
    assert "104 acertos e 16 erros" in pdf_text
    assert "103 acertos e 17 erros" in pdf_text
    assert "dados detalhados da Base" in pdf_text


def test_multisheet_summary_count_aliases_are_checked_and_reported_in_pdf() -> None:
    content = multi_sheet_assessment_workbook(
        summary_headers=("Avaliação", "Corretas", "Incorretas", "Percentual"),
        summary_rows=[("Prova A", 147, 21, 0.875), ("Prova B", 104, 16, 0.8667)],
    )
    web = client()

    inspected = web.post(
        "/api/inspect", files={"file": ("resumo_aliases.xlsx", content)}
    )

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    assert (data["evaluations"][1]["correct"], data["evaluations"][1]["incorrect"]) == (
        103,
        17,
    )
    warning = " ".join(data["warnings"])
    assert "104 acertos e 16 erros" in warning
    assert "103 acertos e 17 erros" in warning
    assert "dados detalhados da Base" in warning

    generated = web.post(
        "/api/generate",
        files={"file": ("resumo_aliases.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resumo com aliases",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(generated.content)).pages
    )
    assert "104 acertos e 16 erros" in pdf_text
    assert "103 acertos e 17 erros" in pdf_text


def test_multisheet_summary_missing_base_evaluation_warns_in_inspection_and_pdf() -> None:
    content = multi_sheet_assessment_workbook(
        summary_rows=[("Prova A", 147, 21, 0.875)]
    )
    web = client()

    inspected = web.post(
        "/api/inspect", files={"file": ("resumo_sem_prova_b.xlsx", content)}
    )

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    assert [item["name"] for item in data["evaluations"]] == ["Prova A", "Prova B"]
    warning = " ".join(data["warnings"])
    assert "Prova B" in warning
    assert "não encontrada no Resumo" in warning
    assert "dados detalhados da Base" in warning

    generated = web.post(
        "/api/generate",
        files={"file": ("resumo_sem_prova_b.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resumo incompleto",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(generated.content)).pages
    )
    assert "Prova B" in pdf_text
    assert "não encontrada no Resumo" in pdf_text


def test_multisheet_summary_warnings_beyond_first_page_remain_in_pdf() -> None:
    evaluation_names = "ABCDEFGHIJKLMNOPQRSTUVWXY"
    base_rows = [
        (index + 1, name, 1, index + 1, 1)
        for index, name in enumerate(evaluation_names)
    ]
    content = multi_sheet_assessment_workbook(
        base_rows=base_rows,
        summary_rows=[("Prova A", 1, 1, 0.5)],
    )
    web = client()

    inspected = web.post(
        "/api/inspect", files={"file": ("muitos_avisos_resumo.xlsx", content)}
    )

    assert inspected.status_code == 200, inspected.text
    warnings = " ".join(inspected.json()["warnings"])
    assert len(inspected.json()["warnings"]) > 24
    assert "Prova Y não encontrada no Resumo" in warnings

    generated = web.post(
        "/api/generate",
        files={"file": ("muitos_avisos_resumo.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resumo com muitos avisos",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(generated.content)).pages
    )
    assert "Prova Y não encontrada no Resumo" in pdf_text


def test_multisheet_assessment_ignores_invalid_auxiliary_candidate_with_warning() -> None:
    content = multi_sheet_assessment_workbook(include_invalid_auxiliary=True)
    web = client()

    inspected = web.post(
        "/api/inspect", files={"file": ("auxiliar_invalida.xlsx", content)}
    )

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    assert data["sheet"] == "Base"
    assert [item["name"] for item in data["evaluations"]] == ["Prova A", "Prova B"]
    assert any("Aba Auxiliar" in warning and "candidata inválida" in warning for warning in data["warnings"])

    generated = web.post(
        "/api/generate",
        files={"file": ("auxiliar_invalida.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Dados válidos",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(generated.content)).pages
    )
    assert "Aba Auxiliar" in pdf_text
    assert "candidata inválida" in pdf_text


def test_multisheet_assessment_rejects_two_valid_detail_sheets() -> None:
    alternate_rows = [(901, "C", 1, 8, 2), (902, "C", 2, 7, 3)]
    content = multi_sheet_assessment_workbook(
        additional_base_sheets=[("OutraBase", alternate_rows)]
    )
    web = client()

    inspected = web.post(
        "/api/inspect", files={"file": ("duas_bases.xlsx", content)}
    )

    assert inspected.status_code == 200, inspected.text
    choices = inspected.json()
    assert choices["kind"] == "assessment_choices"
    assert "selecione" in choices["message"].lower()
    assert [candidate["sheet"] for candidate in choices["candidates"]] == [
        "Base",
        "OutraBase",
    ]
    alternate = choices["candidates"][1]
    assert alternate["evaluations"][0]["name"] == "Prova C"

    selected = web.post(
        "/api/inspect",
        files={"file": ("duas_bases.xlsx", content)},
        data={"candidate_id": alternate["id"]},
    )
    assert selected.status_code == 200, selected.text
    selected_data = selected.json()
    assert selected_data["kind"] == "assessment"
    assert selected_data["sheet"] == "OutraBase"
    assert selected_data["candidate_id"] == alternate["id"]
    assert selected_data["evaluations"][0]["correct"] == 15

    generated = web.post(
        "/api/generate",
        files={"file": ("duas_bases.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "candidate_id": alternate["id"],
                    "title": "Escolha confirmada",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(generated.content)).pages
    )
    assert "Prova C" in pdf_text
    assert "15 acertos" in pdf_text

    different_file = multi_sheet_assessment_workbook(
        base_rows=[(301, "D", 1, 1, 1)]
    )
    mismatched_selection = web.post(
        "/api/inspect",
        files={"file": ("outra_planilha.xlsx", different_file)},
        data={"candidate_id": alternate["id"]},
    )
    assert mismatched_selection.status_code == 422
    assert "não corresponde" in mismatched_selection.json()["detail"].lower()

    stale_generation = web.post(
        "/api/generate",
        files={"file": ("outra_planilha.xlsx", different_file)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "candidate_id": alternate["id"],
                    "title": "Seleção antiga",
                }
            )
        },
    )
    assert stale_generation.status_code == 422
    assert "não corresponde" in stale_generation.json()["detail"].lower()


def test_side_by_side_assessment_inspection_and_pdf_keep_blocks_separate() -> None:
    web = client()
    content = side_by_side_assessment_workbook()

    inspected = web.post(
        "/api/inspect", files={"file": ("comparativo.xlsx", content)}
    )

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    assert data["kind"] == "assessment"
    assert data["sheet"] == "Comparativo"
    assert [item["name"] for item in data["evaluations"]] == [
        "Bloco esquerdo",
        "Bloco direito",
    ]
    left, right = data["evaluations"]
    assert (left["question_count"], left["correct"], left["incorrect"]) == (
        10,
        139,
        21,
    )
    assert (left["response_counts"], left["total_responses"], left["rate"]) == (
        [16],
        160,
        86.88,
    )
    assert (right["question_count"], right["correct"], right["incorrect"]) == (
        9,
        95,
        13,
    )
    assert (right["response_counts"], right["total_responses"], right["rate"]) == (
        [12],
        108,
        87.96,
    )
    assert left["questions"][0]["number"] == right["questions"][0]["number"] == 1
    assert any(
        "números iguais não comprovam" in warning.lower()
        for warning in data["warnings"]
    )
    assert not any("diverge" in warning.lower() for warning in data["warnings"])

    generated = web.post(
        "/api/generate",
        files={"file": ("comparativo.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Comparativo descritivo",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    pages = PdfReader(io.BytesIO(generated.content)).pages
    assert len(pages) == 4
    pdf_text = "\n".join(page.extract_text() or "" for page in pages)
    assert "Bloco esquerdo" in pdf_text and "Bloco direito" in pdf_text
    assert "139 acertos" in pdf_text and "21 erros" in pdf_text
    assert "95 acertos" in pdf_text and "13 erros" in pdf_text
    assert "86,88%" in pdf_text and "87,96%" in pdf_text
    assert "16 respostas por questão" in pdf_text
    assert "12 respostas por questão" in pdf_text


def test_side_by_side_totals_and_reported_rates_warn_without_replacing_details() -> None:
    content = side_by_side_assessment_workbook(
        left_summary=("Resumo", 22, 138, 160),
        right_summary=("TOTAL", 108, 94, 14),
        summary_rates=(0.5, 0.5),
    )
    web = client()

    inspected = web.post(
        "/api/inspect", files={"file": ("resumos_divergentes.xlsx", content)}
    )

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    left, right = data["evaluations"]
    assert (left["correct"], left["incorrect"], left["rate"]) == (139, 21, 86.88)
    assert (right["correct"], right["incorrect"], right["rate"]) == (95, 13, 87.96)
    warning = " ".join(data["warnings"])
    assert "Resumo do Bloco esquerdo informa 138 acertos, 22 erros" in warning
    assert "139 acertos, 21 erros e 160 respostas" in warning
    assert "TOTAL do Bloco direito informa 94 acertos, 14 erros" in warning
    assert "Taxa de acerto A informa 50,00%" in warning
    assert "Taxa de acerto B informa 50,00%" in warning
    assert "O relatório usa as questões detalhadas" in warning

    generated = web.post(
        "/api/generate",
        files={"file": ("resumos_divergentes.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Controles conferidos",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(generated.content)).pages
    )
    assert "Resumo do Bloco esquerdo informa 138 acertos, 22 erros" in pdf_text
    assert "TOTAL do Bloco direito informa 94 acertos, 14 erros" in pdf_text
    assert "50,00%" in pdf_text
    assert "taxas calculadas dos blocos" in pdf_text


@pytest.mark.parametrize(
    ("workbook_options", "expected_detail"),
    [
        (
            {"left_questions": [("Q1", 2, 14, 15)]},
            "total informado (15) diverge de acertos + erros (16)",
        ),
        (
            {"left_questions": [("Atividade 2025", 2, 14, 16)]},
            "rótulo 'atividade 2025' inválido",
        ),
        (
            {"left_questions": [("Q1", 0, 0, 0)]},
            "questão sem respostas",
        ),
        (
            {"left_questions": [("Q1", 1, 15, 16), ("Q1", 1, 15, 16)]},
            "questão 1 duplicada",
        ),
        (
            {"right_header": ("ITEM", "TOTAL", "ACERTOS", "ERROS faltando")},
            "formato parcial",
        ),
        (
            {"right_questions": []},
            "não há questões válidas no bloco direito",
        ),
        (
            {"separator_value": 0},
            "coluna separadora entre os blocos deve permanecer vazia",
        ),
        (
            {"separator_column": False},
            "coluna separadora vazia",
        ),
    ],
)
def test_side_by_side_rejects_invalid_or_incomplete_blocks(
    workbook_options: dict[str, object], expected_detail: str
) -> None:
    content = side_by_side_assessment_workbook(**workbook_options)
    web = client()

    inspected = web.post(
        "/api/inspect", files={"file": ("blocos_invalidos.xlsx", content)}
    )

    assert inspected.status_code == 422
    assert expected_detail in inspected.json()["detail"].lower()

    generated = web.post(
        "/api/generate",
        files={"file": ("blocos_invalidos.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Blocos inválidos",
                }
            )
        },
    )
    assert generated.status_code == 422
    assert expected_detail in generated.json()["detail"].lower()


@pytest.mark.parametrize(
    ("base_rows", "expected_detail"),
    [
        (
            [(101, "A", 1, 5, 0), (102, "A", 1, 4, 1)],
            "pergunta 1 duplicada",
        ),
        ([(101, "A", 1, 1.5, 0)], "inteiro não negativo"),
        ([(101, "A", 1, None, 1)], "inteiro não negativo"),
        ([(101, "A", 1, -1, 2)], "inteiro não negativo"),
        ([(101, "A", 1, 0, 0)], "pergunta sem respostas"),
    ],
)
def test_multisheet_assessment_rejects_invalid_detail_rows(
    base_rows: list[tuple[object, ...]], expected_detail: str
) -> None:
    content = multi_sheet_assessment_workbook(base_rows=base_rows)
    response = client().post(
        "/api/inspect", files={"file": ("base_invalida.xlsx", content)}
    )

    assert response.status_code == 422
    assert expected_detail in response.json()["detail"].lower()


def test_assessment_skips_invalid_auxiliary_sheet_and_reports_it() -> None:
    content = assessment_workbook_with_sheets(
        [
            ("Auxiliar", invalid_assessment_candidate_workbook()),
            ("Avaliacoes", traditional_assessment_workbook()),
        ]
    )
    web = client()

    inspected = web.post("/api/inspect", files={"file": ("multiplas_abas.xlsx", content)})

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    assert data["sheet"] == "Avaliacoes"
    assert data["evaluations"][0]["correct"] == 211
    assert data["evaluations"][0]["incorrect"] == 29
    assert any(
        "Aba Auxiliar" in warning
        and "linha 2" in warning.lower()
        and "ignorada" in warning.lower()
        for warning in data["warnings"]
    )

    generated = web.post(
        "/api/generate",
        files={"file": ("multiplas_abas.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resultados da avaliação",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(generated.content)).pages
    )
    assert "Aba Auxiliar" in pdf_text
    assert "ignorada" in pdf_text.lower()


def test_assessment_skips_multiple_invalid_headers_before_valid_candidate() -> None:
    content = assessment_workbook_with_sheets(
        [
            ("Auxiliar", invalid_assessment_candidate_with_multiple_headers_workbook()),
            ("Avaliacoes", traditional_assessment_workbook()),
        ]
    )
    web = client()

    inspected = web.post(
        "/api/inspect",
        files={"file": ("multiplas_candidatas_invalidas.xlsx", content)},
    )

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    assert data["sheet"] == "Avaliacoes"
    assert data["evaluations"][0]["question_count"] == 12
    assert data["evaluations"][0]["correct"] == 211
    auxiliary_warnings = [
        warning for warning in data["warnings"] if "Aba Auxiliar" in warning
    ]
    assert len(auxiliary_warnings) == 2
    assert any(
        "cabeçalho linha 1" in warning and "linha 2" in warning
        for warning in auxiliary_warnings
    )
    assert any(
        "cabeçalho linha 3" in warning and "linha 4" in warning
        for warning in auxiliary_warnings
    )

    generated = web.post(
        "/api/generate",
        files={"file": ("multiplas_candidatas_invalidas.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resultados da avaliação",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(generated.content)).pages
    )
    assert "Aba Auxiliar" in pdf_text
    assert "cabeçalho linha 1" in pdf_text
    assert "cabeçalho linha 3" in pdf_text


def test_assessment_rejects_multiple_valid_sheets_as_ambiguous() -> None:
    content = assessment_workbook_with_sheets(
        [
            ("Avaliacao A", traditional_assessment_workbook()),
            ("Avaliacao B", assessment_workbook()),
        ]
    )
    web = client()

    inspected = web.post("/api/inspect", files={"file": ("duas_avaliacoes.xlsx", content)})

    assert inspected.status_code == 422
    detail = inspected.json()["detail"]
    assert "ambígua" in detail.lower()
    assert "Avaliacao A" in detail
    assert "Avaliacao B" in detail

    generated = web.post(
        "/api/generate",
        files={"file": ("duas_avaliacoes.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resultados da avaliação",
                }
            )
        },
    )
    assert generated.status_code == 422
    assert "ambígua" in generated.json()["detail"].lower()


def test_assessment_rejects_multiple_valid_blocks_in_one_sheet_as_ambiguous() -> None:
    headers = ["Questão", "Acertos", "Erros"]
    content = assessment_workbook_with_candidate_blocks(
        [[headers, [1, 6, 4]], [headers, [1, 8, 2]]]
    )
    web = client()

    inspected = web.post(
        "/api/inspect", files={"file": ("dois_blocos_validos.xlsx", content)}
    )

    assert inspected.status_code == 422
    detail = inspected.json()["detail"]
    assert "ambígua" in detail.lower()
    assert "Comparativo" in detail
    assert "cabeçalho na linha 1" in detail
    assert "cabeçalho na linha 3" in detail

    generated = web.post(
        "/api/generate",
        files={"file": ("dois_blocos_validos.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resultados da avaliação",
                }
            )
        },
    )
    assert generated.status_code == 422
    assert "ambígua" in generated.json()["detail"].lower()


def test_assessment_uses_valid_block_and_warns_about_invalid_block() -> None:
    headers = ["Questão", "Acertos", "Erros"]
    content = assessment_workbook_with_candidate_blocks(
        [[headers, [1, 6, 4]], [headers, ["inválida", "inválido", 0]]]
    )
    web = client()

    inspected = web.post(
        "/api/inspect", files={"file": ("bloco_valido_e_invalido.xlsx", content)}
    )

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    assert data["sheet"] == "Comparativo"
    assert len(data["evaluations"]) == 1
    assert data["evaluations"][0]["question_count"] == 1
    assert data["evaluations"][0]["correct"] == 6
    assert data["evaluations"][0]["incorrect"] == 4
    assert len(data["warnings"]) == 1
    warning = data["warnings"][0]
    assert "cabeçalho linha 3" in warning
    assert "candidata inválida" in warning
    assert "linha 4" in warning

    generated = web.post(
        "/api/generate",
        files={"file": ("bloco_valido_e_invalido.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resultados da avaliação",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(generated.content)).pages
    )
    assert "cabeçalho linha 3" in pdf_text
    assert "candidata inválida" in pdf_text


def test_traditional_single_assessment_inspection_and_pdf() -> None:
    web = client()
    content = traditional_assessment_workbook()
    inspected = web.post(
        "/api/inspect", files={"file": ("entrada_tradicional.xlsx", content)}
    )

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    assert data["kind"] == "assessment"
    assert data["sheet"] == "Avaliacoes"
    assert data["suggested_title"] == "Resultados das avaliações por questão"
    assert len(data["evaluations"]) == 1
    evaluation = data["evaluations"][0]
    assert evaluation["name"] == "Avaliação única"
    assert evaluation["question_count"] == 12
    assert evaluation["response_counts"] == [20]
    assert evaluation["correct"] == 211
    assert evaluation["incorrect"] == 29
    assert evaluation["total_responses"] == 240
    assert evaluation["rate"] == 87.92
    assert evaluation["questions"][0] == {
        "number": 1,
        "correct": 20,
        "incorrect": 0,
        "responses": 20,
        "rate": 100.0,
    }
    assert data["warnings"] == []

    generated = web.post(
        "/api/generate",
        files={"file": ("entrada_tradicional.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resultados da avaliação",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    assert generated.headers["content-type"] == "application/pdf"
    reader = PdfReader(io.BytesIO(generated.content))
    assert len(reader.pages) == 2
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Avaliação única" in pdf_text
    assert "12 questões" in pdf_text
    assert "211 acertos" in pdf_text
    assert "29 erros" in pdf_text
    assert "240 respostas no total" in pdf_text
    assert "20 respostas por questão" in pdf_text
    assert "87,92%" in pdf_text


@pytest.mark.parametrize(
    ("workbook_options", "expected_detail"),
    [
        ({"response_mismatch_question": 3}, "linha 6: respostas (19)"),
        ({"duplicate_question": True}, "linha 5: questão 1 duplicada"),
        ({"zero_denominator_question": 4}, "linha 7: questão sem respostas"),
    ],
)
def test_traditional_assessment_rejects_invalid_detail_rows(
    workbook_options: dict[str, object], expected_detail: str
) -> None:
    response = client().post(
        "/api/inspect",
        files={
            "file": (
                "entrada_invalida.xlsx",
                traditional_assessment_workbook(**workbook_options),
            )
        },
    )

    assert response.status_code == 422
    assert expected_detail in response.json()["detail"].lower()


def test_traditional_assessment_summary_divergence_is_visible_in_pdf() -> None:
    web = client()
    content = traditional_assessment_workbook(divergent_total=True)
    inspected = web.post(
        "/api/inspect", files={"file": ("total_divergente.xlsx", content)}
    )

    assert inspected.status_code == 200, inspected.text
    data = inspected.json()
    assert data["evaluations"][0]["correct"] == 211
    assert data["evaluations"][0]["incorrect"] == 29
    assert any(
        "Linha 16" in warning
        and "212 acertos e 28 erros" in warning
        and "211 acertos e 29 erros" in warning
        and "usa a soma das questões" in warning
        for warning in data["warnings"]
    )

    generated = web.post(
        "/api/generate",
        files={"file": ("total_divergente.xlsx", content)},
        data={
            "options": json.dumps(
                {
                    "kind": "assessment",
                    "model": "avaliacao_questoes",
                    "title": "Resultados da avaliação",
                }
            )
        },
    )
    assert generated.status_code == 200, generated.text
    reader = PdfReader(io.BytesIO(generated.content))
    assert len(reader.pages) == 3
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "212 acertos e 28 erros" in pdf_text
    assert "211 acertos e 29 erros" in pdf_text
    assert "usa a soma das questões" in pdf_text


def test_traditional_assessment_allows_missing_response_column() -> None:
    response = client().post(
        "/api/inspect",
        files={
            "file": (
                "sem_respostas.xlsx",
                traditional_assessment_workbook(include_response_count=False),
            )
        },
    )

    assert response.status_code == 200, response.text
    evaluation = response.json()["evaluations"][0]
    assert evaluation["name"] == "Avaliação única"
    assert evaluation["correct"] == 211
    assert evaluation["incorrect"] == 29
    assert evaluation["questions"][0]["incorrect"] == 0
    assert response.json()["warnings"] == []


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
