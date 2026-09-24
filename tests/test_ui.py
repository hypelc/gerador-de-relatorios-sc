from __future__ import annotations

import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gerador_sc.engine import OperationCancelled, ReportService
from gerador_sc.models import ReportArtifact, ReportConfig
from gerador_sc.ui import MainWindow


def _wait_for(app: QApplication, predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert predicate()


def test_main_window_constructs_without_reading_cells() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle() == "Gerador de Relatorios SC"
    assert window.stack.count() == 5
    window.close()
    app.processEvents()


def test_ui_flow_import_preview_export(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "dados.csv"
    source.write_text("Regiao;2020;2021;2022\nA;0;;2\nB;1;2;3\n", encoding="utf-8")
    window = MainWindow()
    window._inspect_file(str(source))

    _wait_for(app, lambda: window.import_result is not None)
    assert window.stack.currentIndex() == 1
    assert window.table_widget.rowCount() == 1
    window._review_next()
    assert window.stack.currentIndex() == 2
    window._build_next()
    _wait_for(app, lambda: window.artifact is not None)
    assert window.stack.currentIndex() == 3
    destination = tmp_path / "saida" / "relatorio.pdf"
    window._go_to(4)
    window.destination_edit.setText(str(destination))
    window._export_pdf()
    _wait_for(app, lambda: window.exported_pdf is not None)
    assert destination.exists()
    window.close()
    app.processEvents()


class _BlockingInspectService(ReportService):
    def __init__(self, started: threading.Event, release: threading.Event):
        super().__init__()
        self.started = started
        self.release = release
        self.calls: list[str] = []

    def inspect(self, path):
        self.calls.append(str(path))
        self.started.set()
        self.release.wait(5)
        return super().inspect(path)


class _BlockingPreviewService(ReportService):
    def __init__(self, started: threading.Event, release: threading.Event):
        super().__init__()
        self.started = started
        self.release = release
        self.cleaned = False

    def preview(self, *args, **kwargs):
        self.started.set()
        self.release.wait(5)
        kwargs.pop("cancel_event", None)
        return super().preview(*args, **kwargs)

    def cleanup(self, artifact):
        self.cleaned = True
        return super().cleanup(artifact)


class _BlockingExportService(ReportService):
    def __init__(self, started: threading.Event):
        super().__init__()
        self.started = started

    def export(self, artifact, destination, *, overwrite=False, progress=None, cancel_event=None):
        del artifact, destination, overwrite, progress
        self.started.set()
        while cancel_event is None or not cancel_event.is_set():
            time.sleep(0.01)
        raise OperationCancelled("Exportacao cancelada pela pessoa usuaria.")


def test_ui_rejects_second_import_while_first_worker_is_active(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    first = tmp_path / "primeiro.csv"
    second = tmp_path / "segundo.csv"
    content = "Regiao;2020;2021;2022\nA;1;2;3\n"
    first.write_text(content, encoding="utf-8")
    second.write_text(content, encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    service = _BlockingInspectService(started, release)
    window = MainWindow(service)

    window._inspect_file(str(first))
    _wait_for(app, started.is_set)
    window._inspect_file(str(second))
    assert service.calls == [str(first)]
    assert "Aguarde" in window.status_label.text()

    release.set()
    _wait_for(app, lambda: window.import_result is not None)
    window.close()
    app.processEvents()


def test_ui_blocks_navigation_and_defers_cleanup_until_preview_worker_finishes(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "dados.csv"
    source.write_text("Regiao;2020;2021;2022\nA;1;2;3\n", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    service = _BlockingPreviewService(started, release)
    window = MainWindow(service)

    window._inspect_file(str(source))
    _wait_for(app, lambda: window.import_result is not None)
    window._review_next()
    window._build_next()
    _wait_for(app, started.is_set)
    assert window.stack.currentIndex() == 3

    window._go_to(2)
    assert window.stack.currentIndex() == 3
    window.close()
    assert window._close_requested

    release.set()
    _wait_for(app, lambda: service.cleaned)
    assert service.cleaned
    assert window.artifact is None


def test_ui_cancel_export_forwards_event_to_service(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    started = threading.Event()
    service = _BlockingExportService(started)
    window = MainWindow(service)
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"pdf")
    window.artifact = ReportArtifact(
        source_pdf,
        tmp_path,
        (),
        1,
        ReportConfig(("table",), years=(2020,), title="Teste"),
    )
    window.destination_edit.setText(str(tmp_path / "saida.pdf"))

    window._export_pdf()
    _wait_for(app, started.is_set)
    window._cancel_worker()
    _wait_for(app, lambda: window._active_worker is None)

    assert window.exported_pdf is None
    assert window.status_label.text() == "Operacao cancelada."
    window.close()
    app.processEvents()


def test_ui_empty_destination_shows_actionable_message(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"pdf")
    window.artifact = ReportArtifact(
        source_pdf,
        tmp_path,
        (),
        1,
        ReportConfig(("table",), years=(2020,), title="Teste"),
    )
    messages: list[tuple[str, str]] = []
    window._show_message = lambda message, title="Conferencia": messages.append((message, title))
    window.destination_edit.clear()

    window._export_pdf()

    assert messages == [("Informe o nome e a pasta do arquivo PDF.", "Destino necessario")]
    assert window._active_worker is None
    window.close()
    app.processEvents()
