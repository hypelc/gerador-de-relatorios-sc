"""Importação e relatório descritivo de avaliações por questão."""

from __future__ import annotations

import csv
import io
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from itertools import chain, islice
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import openpyxl
from matplotlib.backends.backend_pdf import PdfPages


def _key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"\s+", " ", "".join(char for char in text if not unicodedata.combining(char)).strip().lower())


HEADERS = ("avaliacao", "questao", "acertos", "erros")


@dataclass(frozen=True)
class Question:
    number: int
    correct: int
    incorrect: int

    @property
    def responses(self) -> int:
        return self.correct + self.incorrect

    @property
    def rate(self) -> float:
        return 100 * self.correct / self.responses


@dataclass(frozen=True)
class Evaluation:
    name: str
    questions: tuple[Question, ...]

    @property
    def correct(self) -> int:
        return sum(question.correct for question in self.questions)

    @property
    def incorrect(self) -> int:
        return sum(question.incorrect for question in self.questions)

    @property
    def rate(self) -> float:
        return 100 * self.correct / (self.correct + self.incorrect)


@dataclass(frozen=True)
class Assessment:
    sheet: str
    evaluations: tuple[Evaluation, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "assessment",
            "sheet": self.sheet,
            "models": ["avaliacao_questoes"],
            "suggested_title": "Resultados das avaliações por questão",
            "evaluations": [
                {
                    "name": item.name,
                    "question_count": len(item.questions),
                    "response_counts": sorted({question.responses for question in item.questions}),
                    "correct": item.correct,
                    "incorrect": item.incorrect,
                    "rate": round(item.rate, 2),
                    "questions": [
                        {"number": question.number, "correct": question.correct, "incorrect": question.incorrect, "rate": round(question.rate, 2)}
                        for question in item.questions
                    ],
                }
                for item in self.evaluations
            ],
            "warnings": list(self.warnings),
        }


def _rows(path: Path):
    if path.suffix.lower() == ".xlsx":
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in workbook:
                yield sheet.title, sheet.iter_rows(values_only=True)
        finally:
            workbook.close()
    else:
        raw = path.read_text(encoding="utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(raw[:4096], delimiters=";,\t")
        except csv.Error:
            dialect = csv.excel
        yield path.stem, csv.reader(io.StringIO(raw), dialect)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        # ValueError vira resposta 422 na API, assim como os demais dados inválidos.
        raise ValueError(f"{label}: informe um número inteiro não negativo.")  # noqa: TRY004
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label}: informe um número inteiro não negativo.") from error
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError(f"{label}: informe um número inteiro não negativo.")
    return int(number)


def _percent(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", ".")
    if text.count("%") > 1:
        return None
    try:
        number = float(text.rstrip("%"))
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number if text.endswith("%") else number * 100 if number <= 1 else number


def _cell(row: tuple[object, ...], column: int | None) -> object:
    return row[column] if column is not None and column < len(row) else None


def _check_percentages(
    row: tuple[object, ...],
    columns: dict[str, int],
    row_index: int,
    correct: int,
    incorrect: int,
    warnings: list[str],
) -> None:
    responses = correct + incorrect
    for heading, count in (("% acerto", correct), ("% erro", incorrect)):
        raw = _cell(row, columns.get(heading))
        if raw is None or str(raw).strip() == "":
            continue
        informed = _percent(raw)
        expected = 100 * count / responses if responses else None
        if informed is None or expected is None or abs(informed - expected) > 0.0051:
            warnings.append(f"Linha {row_index}: {heading} divergente ou inválido; foi recalculado.")


def read_assessment(path: Path) -> Assessment | None:
    """Reconhece o contrato por cabeçalhos; não adivinha tabelas sem eles."""
    for sheet, row_iterator in _rows(path):
        first_rows = tuple(islice(row_iterator, 30))
        for header_index, header in enumerate(first_rows):
            columns = {_key(value): index for index, value in enumerate(header) if _key(value)}
            if not all(name in columns for name in HEADERS):
                continue
            groups: dict[str, list[Question]] = {}
            totals: dict[str, tuple[int, int, int]] = {}
            warnings: list[str] = []
            last_group = ""
            for row_index, row in enumerate(chain(first_rows[header_index + 1:], row_iterator), start=header_index + 2):
                name = str(_cell(row, columns["avaliacao"]) or "").strip()
                question_value = _cell(row, columns["questao"])
                if not name and all(value is None or str(value).strip() == "" for value in row):
                    continue
                total_in_name = _key(name).startswith("total") and (question_value is None or str(question_value).strip() == "")
                total_in_question = _key(question_value).startswith("total")
                if total_in_name or total_in_question:
                    marker = name if total_in_name else str(question_value)
                    explicit_group = re.sub(r"^total\s*", "", marker, flags=re.IGNORECASE).strip()
                    group_name = explicit_group or (name if total_in_question else last_group)
                    if not group_name:
                        raise ValueError(f"Aba {sheet}, linha {row_index}: total sem avaliação identificável.")
                    correct = _integer(_cell(row, columns["acertos"]), f"Aba {sheet}, linha {row_index}, Acertos")
                    incorrect = _integer(_cell(row, columns["erros"]), f"Aba {sheet}, linha {row_index}, Erros")
                    totals[_key(group_name)] = (correct, incorrect, row_index)
                    _check_percentages(row, columns, row_index, correct, incorrect, warnings)
                    continue
                if not name:
                    raise ValueError(f"Aba {sheet}, linha {row_index}: avaliação ausente.")
                if question_value is None or str(question_value).strip() == "":
                    raise ValueError(f"Aba {sheet}, linha {row_index}: número da questão ausente.")
                number = _integer(question_value, f"Aba {sheet}, linha {row_index}, Questão")
                if number == 0:
                    raise ValueError(f"Aba {sheet}, linha {row_index}: a questão deve começar em 1.")
                correct = _integer(_cell(row, columns["acertos"]), f"Aba {sheet}, linha {row_index}, Acertos")
                incorrect = _integer(_cell(row, columns["erros"]), f"Aba {sheet}, linha {row_index}, Erros")
                if correct + incorrect == 0:
                    raise ValueError(f"Aba {sheet}, linha {row_index}: questão sem respostas.")
                questions = groups.setdefault(name, [])
                if any(item.number == number for item in questions):
                    raise ValueError(f"Aba {sheet}, linha {row_index}: questão {number} duplicada em {name}.")
                questions.append(Question(number, correct, incorrect))
                last_group = name
                _check_percentages(row, columns, row_index, correct, incorrect, warnings)
            if not groups:
                raise ValueError(f"Aba {sheet}: nenhuma questão válida encontrada.")
            evaluations = tuple(Evaluation(name, tuple(sorted(questions, key=lambda item: item.number))) for name, questions in groups.items())
            for item in evaluations:
                total = totals.get(_key(item.name))
                if total and (total[0] != item.correct or total[1] != item.incorrect):
                    warnings.append(f"Linha {total[2]}: total de {item.name} diverge das questões; foi recalculado.")
                if len({question.responses for question in item.questions}) > 1:
                    warnings.append(f"{item.name}: o número de respostas varia entre questões.")
            for group_name in totals:
                if group_name not in {_key(item.name) for item in evaluations}:
                    warnings.append(f"Total de {group_name} sem questões correspondentes; não foi utilizado.")
            if len(evaluations) > 1:
                warnings.append("A planilha não informa o texto das perguntas; números iguais não comprovam questões equivalentes nem evolução individual.")
            return Assessment(sheet, evaluations, tuple(warnings))
    return None


def _percent_label(value: float) -> str:
    return f"{value:.1f}%".replace(".", ",")


def render_assessment_report(
    assessment: Assessment,
    target: Path,
    *,
    title: str,
    authors: str,
    source: str,
    source_name: str,
) -> None:
    if not assessment.evaluations:
        raise ValueError("Nenhuma avaliação disponível para o relatório.")
    with PdfPages(target) as pdf:
        fig = plt.figure(figsize=(11.69, 8.27))
        fig.patch.set_facecolor("white")
        fig.text(0.07, 0.92, title, fontsize=17, weight="bold", color="#16324F")
        fig.text(0.07, 0.87, "Resumo descritivo das avaliações", fontsize=11, color="#4A647A")
        axis = fig.add_axes((0.12, 0.39, 0.80, 0.37))
        names = [item.name for item in assessment.evaluations]
        rates = [item.rate for item in assessment.evaluations]
        bars = axis.barh(names, rates, color="#227C9D")
        axis.invert_yaxis()
        axis.set_xlim(0, 112)
        axis.set_xlabel("Acertos / (acertos + erros) (%)")
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.grid(axis="x", color="#DCE5EB")
        axis.set_axisbelow(True)
        for bar, item in zip(bars, assessment.evaluations):
            axis.text(bar.get_width() + 1.5, bar.get_y() + bar.get_height() / 2, _percent_label(item.rate), va="center", fontsize=10, weight="bold")
        details = "   |   ".join(
            f"{item.name}: {len(item.questions)} questões, {item.correct} acertos, {item.incorrect} erros, "
            f"{min(q.responses for q in item.questions)}–{max(q.responses for q in item.questions)} respostas/questão"
            for item in assessment.evaluations
        )
        fig.text(0.07, 0.29, details, fontsize=8.6, color="#34495E", wrap=True)
        if len(assessment.evaluations) > 1:
            fig.text(0.07, 0.21, "Leitura: sem o texto das perguntas, não é possível afirmar equivalência nem evolução individual.", fontsize=9, color="#8A4F16")
        fig.text(0.07, 0.14, f"Fonte: {source or source_name}   |   Autores: {authors or 'Não informado'}", fontsize=8, color="#526879")
        fig.text(0.07, 0.10, f"Gerado em {datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y')} · Percentuais recalculados a partir de acertos e erros.", fontsize=8, color="#526879")
        pdf.savefig(fig)
        plt.close(fig)

        for item in assessment.evaluations:
            fig = plt.figure(figsize=(11.69, 8.27))
            fig.patch.set_facecolor("white")
            fig.text(0.07, 0.92, f"{item.name} · acertos por questão", fontsize=17, weight="bold", color="#16324F")
            response_counts = sorted({question.responses for question in item.questions})
            response_note = f"{response_counts[0]} respostas por questão" if len(response_counts) == 1 else f"{response_counts[0]} a {response_counts[-1]} respostas por questão"
            fig.text(0.07, 0.87, f"{len(item.questions)} questões · {_percent_label(item.rate)} de acertos · {response_note}", fontsize=10, color="#4A647A")
            axis = fig.add_axes((0.08, 0.22, 0.86, 0.54))
            labels = [str(question.number) for question in item.questions]
            rates = [question.rate for question in item.questions]
            bars = axis.bar(labels, rates, color="#227C9D")
            axis.set_ylim(0, 112)
            axis.set_ylabel("Acertos (%)")
            axis.set_xlabel("Questão")
            axis.spines[["top", "right"]].set_visible(False)
            axis.grid(axis="y", color="#DCE5EB")
            axis.set_axisbelow(True)
            for bar, question in zip(bars, item.questions):
                axis.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, _percent_label(question.rate), ha="center", fontsize=7)
            if len(assessment.evaluations) > 1:
                fig.text(0.07, 0.12, "Números iguais não garantem que perguntas de avaliações diferentes sejam equivalentes.", fontsize=9, color="#8A4F16")
            fig.text(0.07, 0.08, f"Fonte: {source or source_name}   |   Autores: {authors or 'Não informado'}", fontsize=8, color="#526879")
            pdf.savefig(fig)
            plt.close(fig)

        if assessment.warnings:
            fig = plt.figure(figsize=(11.69, 8.27))
            fig.text(0.07, 0.92, "Conferência dos dados", fontsize=17, weight="bold", color="#16324F")
            fig.text(0.07, 0.86, "Avisos encontrados na planilha de origem", fontsize=10, color="#4A647A")
            for index, warning in enumerate(assessment.warnings[:24]):
                fig.text(0.08, 0.80 - index * 0.027, f"• {warning}", fontsize=8.2, color="#34495E")
            pdf.savefig(fig)
            plt.close(fig)
