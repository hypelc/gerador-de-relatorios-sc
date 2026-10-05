"""Importação e relatório descritivo de avaliações por questão."""

from __future__ import annotations

import csv
import hashlib
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


REQUIRED_HEADERS = ("questao", "acertos", "erros")
SINGLE_EVALUATION_NAME = "Avaliação única"
BASE_HEADER_ALIASES = {
    "id": ("id",),
    "evaluation": ("prova", "avaliacao"),
    "question": ("pergunta", "questao"),
    "correct": ("corretas", "acertos"),
    "incorrect": ("incorretas", "erros"),
}
SUMMARY_HEADER_ALIASES = {
    "evaluation": ("avaliacao", "prova"),
    "correct": ("acertos", "corretas"),
    "incorrect": ("erros", "incorretas"),
}


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
    def responses(self) -> int:
        return self.correct + self.incorrect

    @property
    def rate(self) -> float:
        return 100 * self.correct / self.responses


@dataclass(frozen=True)
class Assessment:
    sheet: str
    evaluations: tuple[Evaluation, ...]
    warnings: tuple[str, ...]
    candidate_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
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
                    "total_responses": item.responses,
                    "rate": round(item.rate, 2),
                    "questions": [
                        {
                            "number": question.number,
                            "correct": question.correct,
                            "incorrect": question.incorrect,
                            "responses": question.responses,
                            "rate": round(question.rate, 2),
                        }
                        for question in item.questions
                    ],
                }
                for item in self.evaluations
            ],
            "warnings": list(self.warnings),
        }
        if self.candidate_id is not None:
            result["candidate_id"] = self.candidate_id
        return result


class AssessmentSelectionRequired(ValueError):
    def __init__(self, candidates: list[dict[str, object]]) -> None:
        super().__init__(
            "Mais de uma tabela de avaliação válida foi encontrada. Selecione "
            "qual aba ou bloco detalhado deseja usar."
        )
        self.candidates = candidates


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


def _resolve_header_columns(
    header: tuple[object, ...], aliases: dict[str, tuple[str, ...]], label: str
) -> dict[str, int]:
    normalized = [_key(value) for value in header]
    columns: dict[str, int] = {}
    for field, field_aliases in aliases.items():
        matches = [
            index for index, heading in enumerate(normalized) if heading in field_aliases
        ]
        if not matches:
            raise ValueError(f"{label}: coluna obrigatória ausente ({field}).")
        if len(matches) > 1:
            names = ", ".join(str(header[index]) for index in matches)
            raise ValueError(f"{label}: mais de uma coluna compatível com {field}: {names}.")
        columns[field] = matches[0]
    return columns


def _is_base_header(header: tuple[object, ...]) -> bool:
    headings = {_key(value) for value in header if _key(value)}
    return all(any(alias in headings for alias in aliases) for aliases in BASE_HEADER_ALIASES.values())


def _rows_after_candidate(
    first_rows: tuple[tuple[object, ...], ...],
    row_iterator,
    header_index: int,
    next_header_index: int | None,
):
    if next_header_index is None:
        return chain(first_rows[header_index + 1 :], row_iterator)
    return iter(first_rows[header_index + 1 : next_header_index])


def _evaluation_key(value: object) -> str:
    normalized = _key(value)
    return re.sub(r"^(?:prova|avaliacao)\s+", "", normalized)


def _evaluation_label(value: str) -> str:
    return value if _key(value).startswith("prova ") else f"Prova {value}"


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_identifier(
    digest: str, sheet: str, header_row: int, candidate_type: str
) -> str:
    identity = f"{digest}\0{sheet}\0{header_row}\0{candidate_type}".encode()
    return hashlib.sha256(identity).hexdigest()[:32]


def _candidate_option(
    candidate_id: str, assessment: Assessment, header_row: int
) -> dict[str, object]:
    return {
        "id": candidate_id,
        "sheet": assessment.sheet,
        "header_row": header_row,
        "evaluations": [
            {
                "name": item.name,
                "question_count": len(item.questions),
                "correct": item.correct,
                "incorrect": item.incorrect,
                "total_responses": item.responses,
                "rate": round(item.rate, 2),
            }
            for item in assessment.evaluations
        ],
    }


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
            calculated = "indisponível" if expected is None else f"{expected:.2f}%"
            warnings.append(
                f"Linha {row_index}: {heading} informado {raw!r}; valor calculado "
                f"{calculated}. O relatório usa o valor calculado pelas contagens."
            )


def _check_response_count(
    row: tuple[object, ...],
    columns: dict[str, int],
    sheet: str,
    row_index: int,
    correct: int,
    incorrect: int,
) -> None:
    raw = _cell(row, columns.get("respostas"))
    if raw is None or str(raw).strip() == "":
        return
    informed = _integer(raw, f"Aba {sheet}, linha {row_index}, Respostas")
    expected = correct + incorrect
    if informed != expected:
        raise ValueError(
            f"Aba {sheet}, linha {row_index}: Respostas ({informed}) diverge de "
            f"Acertos + Erros ({expected})."
        )


def _parse_assessment_candidate(
    sheet: str,
    first_rows: tuple[tuple[object, ...], ...],
    row_iterator,
    header_index: int,
    next_header_index: int | None,
) -> Assessment:
    header = first_rows[header_index]
    columns = {_key(value): index for index, value in enumerate(header) if _key(value)}
    evaluation_column = columns.get("avaliacao")
    groups: dict[str, list[Question]] = {}
    totals: dict[str, tuple[int, int, int]] = {}
    warnings: list[str] = []
    last_group = ""
    if next_header_index is None:
        rows_after_header = chain(first_rows[header_index + 1 :], row_iterator)
    else:
        rows_after_header = iter(first_rows[header_index + 1 : next_header_index])
    for row_index, row in enumerate(rows_after_header, start=header_index + 2):
        name = (
            str(_cell(row, evaluation_column) or "").strip()
            if evaluation_column is not None
            else SINGLE_EVALUATION_NAME
        )
        question_value = _cell(row, columns["questao"])
        if all(value is None or str(value).strip() == "" for value in row):
            continue
        total_in_name = _key(name).startswith("total") and (
            question_value is None or str(question_value).strip() == ""
        )
        total_in_question = _key(question_value).startswith("total")
        if total_in_name or total_in_question:
            marker = name if total_in_name else str(question_value)
            explicit_group = re.sub(
                r"^total\s*", "", marker, flags=re.IGNORECASE
            ).strip()
            group_name = explicit_group or (name if total_in_question else last_group)
            if not group_name:
                raise ValueError(
                    f"Aba {sheet}, linha {row_index}: total sem avaliação identificável."
                )
            correct = _integer(
                _cell(row, columns["acertos"]),
                f"Aba {sheet}, linha {row_index}, Acertos",
            )
            incorrect = _integer(
                _cell(row, columns["erros"]),
                f"Aba {sheet}, linha {row_index}, Erros",
            )
            _check_response_count(
                row, columns, sheet, row_index, correct, incorrect
            )
            totals[_key(group_name)] = (correct, incorrect, row_index)
            _check_percentages(row, columns, row_index, correct, incorrect, warnings)
            continue
        if not name:
            raise ValueError(f"Aba {sheet}, linha {row_index}: avaliação ausente.")
        if question_value is None or str(question_value).strip() == "":
            raise ValueError(
                f"Aba {sheet}, linha {row_index}: número da questão ausente."
            )
        number = _integer(
            question_value, f"Aba {sheet}, linha {row_index}, Questão"
        )
        if number == 0:
            raise ValueError(
                f"Aba {sheet}, linha {row_index}: a questão deve começar em 1."
            )
        correct = _integer(
            _cell(row, columns["acertos"]),
            f"Aba {sheet}, linha {row_index}, Acertos",
        )
        incorrect = _integer(
            _cell(row, columns["erros"]),
            f"Aba {sheet}, linha {row_index}, Erros",
        )
        _check_response_count(row, columns, sheet, row_index, correct, incorrect)
        if correct + incorrect == 0:
            raise ValueError(f"Aba {sheet}, linha {row_index}: questão sem respostas.")
        questions = groups.setdefault(name, [])
        if any(item.number == number for item in questions):
            raise ValueError(
                f"Aba {sheet}, linha {row_index}: questão {number} duplicada em {name}."
            )
        questions.append(Question(number, correct, incorrect))
        last_group = name
        _check_percentages(row, columns, row_index, correct, incorrect, warnings)
    if not groups:
        raise ValueError(f"Aba {sheet}: nenhuma questão válida encontrada.")
    evaluations = tuple(
        Evaluation(name, tuple(sorted(questions, key=lambda item: item.number)))
        for name, questions in groups.items()
    )
    for item in evaluations:
        total = totals.get(_key(item.name))
        if total and (total[0] != item.correct or total[1] != item.incorrect):
            warnings.append(
                f"Linha {total[2]}: total informado para {item.name}: "
                f"{total[0]} acertos e {total[1]} erros; soma das questões: "
                f"{item.correct} acertos e {item.incorrect} erros. "
                "O relatório usa a soma das questões."
            )
        if len({question.responses for question in item.questions}) > 1:
            warnings.append(f"{item.name}: o número de respostas varia entre questões.")
    for group_name in totals:
        if group_name not in {_key(item.name) for item in evaluations}:
            warnings.append(
                f"Total de {group_name} sem questões correspondentes; não foi utilizado."
            )
    if len(evaluations) > 1:
        warnings.append(
            "A planilha não informa o texto das perguntas; números iguais não comprovam "
            "questões equivalentes nem evolução individual."
        )
    return Assessment(sheet, evaluations, tuple(warnings))


def _parse_base_candidate(
    sheet: str,
    first_rows: tuple[tuple[object, ...], ...],
    row_iterator,
    header_index: int,
    next_header_index: int | None,
) -> Assessment:
    header = first_rows[header_index]
    columns = _resolve_header_columns(
        header, BASE_HEADER_ALIASES, f"Aba {sheet}, cabeçalho linha {header_index + 1}"
    )
    groups: dict[str, tuple[str, list[Question], set[int]]] = {}
    rows = _rows_after_candidate(
        first_rows, row_iterator, header_index, next_header_index
    )
    for row_index, row in enumerate(rows, start=header_index + 2):
        if all(value is None or str(value).strip() == "" for value in row):
            continue
        raw_name = str(_cell(row, columns["evaluation"]) or "").strip()
        if not raw_name:
            raise ValueError(f"Aba {sheet}, linha {row_index}: prova ausente.")
        question_value = _cell(row, columns["question"])
        if question_value is None or str(question_value).strip() == "":
            raise ValueError(
                f"Aba {sheet}, linha {row_index}: número da pergunta ausente."
            )
        number = _integer(
            question_value, f"Aba {sheet}, linha {row_index}, Pergunta"
        )
        if number == 0:
            raise ValueError(
                f"Aba {sheet}, linha {row_index}: a pergunta deve começar em 1."
            )
        correct = _integer(
            _cell(row, columns["correct"]), f"Aba {sheet}, linha {row_index}, Corretas"
        )
        incorrect = _integer(
            _cell(row, columns["incorrect"]),
            f"Aba {sheet}, linha {row_index}, Incorretas",
        )
        if correct + incorrect == 0:
            raise ValueError(f"Aba {sheet}, linha {row_index}: pergunta sem respostas.")
        group_key = _evaluation_key(raw_name)
        display_name = _evaluation_label(raw_name)
        group = groups.setdefault(group_key, (display_name, [], set()))
        if number in group[2]:
            raise ValueError(
                f"Aba {sheet}, linha {row_index}: pergunta {number} duplicada em "
                f"{display_name}."
            )
        group[1].append(Question(number, correct, incorrect))
        group[2].add(number)

    if not groups:
        raise ValueError(f"Aba {sheet}: nenhuma pergunta válida encontrada.")
    evaluations = tuple(
        Evaluation(name, tuple(sorted(questions, key=lambda item: item.number)))
        for name, questions, _ in groups.values()
    )
    warnings = []
    for evaluation in evaluations:
        if len({question.responses for question in evaluation.questions}) > 1:
            warnings.append(
                f"{evaluation.name}: o número de respostas varia entre questões."
            )
    if len(evaluations) > 1:
        warnings.append(
            "A planilha não informa o texto das perguntas; números iguais não comprovam "
            "questões equivalentes nem evolução individual."
        )
    return Assessment(sheet, evaluations, tuple(warnings))


def _is_metadata_header(row: tuple[object, ...]) -> bool:
    return (
        _key(_cell(row, 0)) == "observacao"
        and _key(_cell(row, 1)) == "valor"
        and _key(_cell(row, 2)) == "tipo"
    )


def _check_base_summaries(path: Path, assessment: Assessment) -> list[str]:
    detail_by_key = {
        _evaluation_key(item.name): item for item in assessment.evaluations
    }
    warnings: list[str] = []
    summary_found = False
    matched_evaluations: set[str] = set()
    for sheet, row_iterator in _rows(path):
        first_rows = tuple(islice(row_iterator, 30))
        summary_headers: list[tuple[int, dict[str, int], int | None]] = []
        for header_index, header in enumerate(first_rows):
            headings = {_key(value) for value in header if _key(value)}
            if any(heading in {"id", "questao", "pergunta"} for heading in headings):
                continue
            if not all(
                any(alias in headings for alias in aliases)
                for aliases in SUMMARY_HEADER_ALIASES.values()
            ):
                continue
            label = f"Aba {sheet}, cabeçalho linha {header_index + 1}"
            try:
                columns = _resolve_header_columns(
                    header, SUMMARY_HEADER_ALIASES, label
                )
            except ValueError as error:
                warnings.append(f"{error} O resumo não foi usado como conferência.")
                continue
            summary_found = True
            percentage_columns = [
                index
                for index, heading in enumerate(header)
                if _key(heading) in {"percentual", "percentagem", "percent", "% acerto"}
            ]
            if len(percentage_columns) > 1:
                warnings.append(
                    f"{label}: há mais de uma coluna de percentual; os percentuais "
                    "do resumo não foram conferidos."
                )
            percent_column = percentage_columns[0] if len(percentage_columns) == 1 else None
            summary_headers.append((header_index, columns, percent_column))

        for candidate_index, (header_index, columns, percent_column) in enumerate(
            summary_headers
        ):
            next_header_index = (
                summary_headers[candidate_index + 1][0]
                if candidate_index + 1 < len(summary_headers)
                else None
            )
            rows = _rows_after_candidate(
                first_rows, row_iterator, header_index, next_header_index
            )
            for row_index, row in enumerate(rows, start=header_index + 2):
                if _is_metadata_header(row):
                    break
                if all(value is None or str(value).strip() == "" for value in row):
                    continue
                raw_name = str(_cell(row, columns["evaluation"]) or "").strip()
                if not raw_name:
                    warnings.append(
                        f"Aba {sheet}, linha {row_index}: rótulo de avaliação ausente "
                        "no resumo; linha não conferida."
                    )
                    continue
                evaluation_key = _evaluation_key(raw_name)
                evaluation = detail_by_key.get(evaluation_key)
                if evaluation is None:
                    warnings.append(
                        f"Aba {sheet}, linha {row_index}: {raw_name} não tem grupo "
                        f"correspondente na {assessment.sheet}; resumo não utilizado."
                    )
                    continue
                matched_evaluations.add(evaluation_key)
                try:
                    correct = _integer(
                        _cell(row, columns["correct"]),
                        f"Aba {sheet}, linha {row_index}, Acertos do resumo",
                    )
                    incorrect = _integer(
                        _cell(row, columns["incorrect"]),
                        f"Aba {sheet}, linha {row_index}, Erros do resumo",
                    )
                except ValueError as error:
                    warnings.append(
                        f"Aba {sheet}, linha {row_index}: resumo não conferido "
                        f"({error}). Os dados detalhados da {assessment.sheet} continuam "
                        "sendo usados."
                    )
                    continue
                if (correct, incorrect) != (evaluation.correct, evaluation.incorrect):
                    warnings.append(
                        f"Aba {sheet}, linha {row_index}: {raw_name} informa {correct} "
                        f"acertos e {incorrect} erros; soma das questões da "
                        f"{assessment.sheet}: {evaluation.correct} acertos e "
                        f"{evaluation.incorrect} erros. O relatório usa os dados "
                        f"detalhados da {assessment.sheet}."
                    )
                if percent_column is not None:
                    raw_percent = _cell(row, percent_column)
                    if raw_percent is None or str(raw_percent).strip() == "":
                        continue
                    informed = _percent(raw_percent)
                    if informed is None:
                        warnings.append(
                            f"Aba {sheet}, linha {row_index}: percentual do resumo "
                            f"inválido ({raw_percent!r}); o relatório usa os dados "
                            f"detalhados da {assessment.sheet}."
                        )
                    elif abs(informed - evaluation.rate) > 0.0051:
                        warnings.append(
                            f"Aba {sheet}, linha {row_index}: percentual do resumo "
                            f"({informed:.2f}%) diverge do calculado pelas questões "
                            f"({evaluation.rate:.2f}%). O relatório usa os dados "
                            f"detalhados da {assessment.sheet}."
                        )
    if summary_found:
        for evaluation_key, evaluation in detail_by_key.items():
            if evaluation_key not in matched_evaluations:
                warnings.append(
                    f"{evaluation.name} não encontrada no Resumo; o relatório usa "
                    f"os dados detalhados da {assessment.sheet}."
                )
    return warnings


def read_assessment(
    path: Path, candidate_id: str | None = None
) -> Assessment | None:
    """Valida candidatos nas abas e evita escolher pela ordem do arquivo."""
    valid_candidates: list[tuple[Assessment, int, str]] = []
    invalid_candidates: list[tuple[str, int, str]] = []

    for sheet, row_iterator in _rows(path):
        first_rows = tuple(islice(row_iterator, 30))
        candidate_headers: list[tuple[int, str]] = []
        for header_index, header in enumerate(first_rows):
            columns = {_key(value) for value in header if _key(value)}
            if _is_base_header(header):
                candidate_headers.append((header_index, "base_multisheet"))
            elif all(name in columns for name in REQUIRED_HEADERS):
                candidate_headers.append((header_index, "traditional"))
        if not candidate_headers:
            continue
        for candidate_index, (header_index, candidate_type) in enumerate(
            candidate_headers
        ):
            next_header_index = (
                candidate_headers[candidate_index + 1][0]
                if candidate_index + 1 < len(candidate_headers)
                else None
            )
            candidate_rows = iter(()) if next_header_index is not None else row_iterator
            try:
                if candidate_type == "base_multisheet":
                    candidate = _parse_base_candidate(
                        sheet,
                        first_rows,
                        candidate_rows,
                        header_index,
                        next_header_index,
                    )
                else:
                    candidate = _parse_assessment_candidate(
                        sheet,
                        first_rows,
                        candidate_rows,
                        header_index,
                        next_header_index,
                    )
            except ValueError as error:
                invalid_candidates.append((sheet, header_index + 1, str(error)))
            else:
                valid_candidates.append((candidate, header_index + 1, candidate_type))

    if not valid_candidates:
        if candidate_id is not None:
            raise ValueError(
                "A seleção da aba ou bloco não corresponde a uma tabela válida "
                "nesta planilha."
            )
        if not invalid_candidates:
            return None
        if len(invalid_candidates) == 1:
            raise ValueError(invalid_candidates[0][2])
        details = " | ".join(
            f"Aba {sheet}, cabeçalho linha {header_row}: {error}"
            for sheet, header_row, error in invalid_candidates
        )
        raise ValueError(
            "Nenhuma tabela de avaliação válida foi encontrada. " + details
        )

    file_digest: str | None = None
    candidate_ids: list[str] = []
    if candidate_id is not None or len(valid_candidates) > 1:
        file_digest = _file_digest(path)
        candidate_ids = [
            _candidate_identifier(file_digest, candidate.sheet, header_row, kind)
            for candidate, header_row, kind in valid_candidates
        ]

    if candidate_id is not None:
        matching_indices = [
            index
            for index, possible_id in enumerate(candidate_ids)
            if possible_id == candidate_id
        ]
        if len(matching_indices) != 1:
            raise ValueError(
                "A seleção da aba ou bloco não corresponde a uma tabela válida "
                "nesta planilha."
            )
        selected_index = matching_indices[0]
    elif len(valid_candidates) > 1:
        if any(candidate_type == "base_multisheet" for _, _, candidate_type in valid_candidates):
            assert file_digest is not None
            raise AssessmentSelectionRequired(
                [
                    _candidate_option(candidate_ids[index], candidate, header_row)
                    for index, (candidate, header_row, _) in enumerate(valid_candidates)
                ]
            )
        details = ", ".join(
            f"{candidate.sheet} (cabeçalho na linha {header_row})"
            for candidate, header_row, _ in valid_candidates
        )
        raise ValueError(
            "Mais de uma tabela de avaliação válida foi encontrada: "
            f"{details}. A seleção é ambígua; não foi escolhido nenhum candidato."
        )
    else:
        selected_index = 0

    selected, _, selected_type = valid_candidates[selected_index]
    warnings = list(selected.warnings)
    for sheet, header_row, error in invalid_candidates:
        detail = error
        for prefix in (f"Aba {sheet}, ", f"Aba {sheet}: "):
            if detail.startswith(prefix):
                detail = detail[len(prefix) :]
                break
        warnings.append(
            f"Aba {sheet}, cabeçalho linha {header_row}: candidata inválida e "
            f"ignorada ({detail})."
        )
    if selected_type == "base_multisheet":
        warnings.extend(_check_base_summaries(path, selected))
    return Assessment(
        selected.sheet,
        selected.evaluations,
        tuple(warnings),
        candidate_id if candidate_id is not None else None,
    )


def _percent_label(value: float) -> str:
    return f"{value:.2f}%".replace(".", ",")


def _response_note(evaluation: Evaluation) -> str:
    response_counts = sorted({question.responses for question in evaluation.questions})
    if len(response_counts) == 1:
        return f"{response_counts[0]} respostas por questão"
    return f"{response_counts[0]} a {response_counts[-1]} respostas por questão"


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
        details = "\n".join(
            f"{item.name}: {len(item.questions)} questões, {item.correct} acertos, "
            f"{item.incorrect} erros, {item.responses} respostas no total, "
            f"{_response_note(item)}"
            for item in assessment.evaluations
        )
        fig.text(
            0.07,
            0.29,
            details,
            fontsize=8.6,
            color="#34495E",
            linespacing=1.35,
            wrap=True,
        )
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
            response_note = _response_note(item)
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
                axis.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 1,
                    f"{_percent_label(question.rate)}\n{question.correct}/{question.responses}",
                    ha="center",
                    fontsize=7,
                )
            if len(assessment.evaluations) > 1:
                fig.text(0.07, 0.12, "Números iguais não garantem que perguntas de avaliações diferentes sejam equivalentes.", fontsize=9, color="#8A4F16")
            fig.text(0.07, 0.08, f"Fonte: {source or source_name}   |   Autores: {authors or 'Não informado'}", fontsize=8, color="#526879")
            pdf.savefig(fig)
            plt.close(fig)

        if assessment.warnings:
            warnings_per_page = 24
            page_count = (len(assessment.warnings) + warnings_per_page - 1) // warnings_per_page
            for page_index, start in enumerate(
                range(0, len(assessment.warnings), warnings_per_page), start=1
            ):
                fig = plt.figure(figsize=(11.69, 8.27))
                fig.text(0.07, 0.92, "Conferência dos dados", fontsize=17, weight="bold", color="#16324F")
                fig.text(
                    0.07,
                    0.86,
                    f"Avisos encontrados na planilha de origem ({page_index}/{page_count})",
                    fontsize=10,
                    color="#4A647A",
                )
                for index, warning in enumerate(
                    assessment.warnings[start : start + warnings_per_page]
                ):
                    fig.text(0.08, 0.80 - index * 0.027, f"• {warning}", fontsize=8.2, color="#34495E")
                pdf.savefig(fig)
                plt.close(fig)
