"""Interface Qt Widgets em cinco etapas, sem logica de leitura de celulas."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, QTimer, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, APP_VERSION
from .engine import OperationCancelled, ReportService, default_export_path
from .models import Diagnostic, ImportResult, ReportArtifact, ReportConfig, ReportValidationError
from .rendering import PALETTES, RenderCancelled


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(object)
    progress = Signal(int, str)
    finished = Signal()


class FunctionWorker(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.cancel_event = threading.Event()
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.function(self.signals.progress.emit, self.cancel_event)
        except BaseException as error:  # noqa: BLE001 - propaga a excecao para a tela
            self.signals.error.emit(error)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


def _button(text: str, primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setMinimumHeight(38)
    if primary:
        button.setObjectName("primaryButton")
    return button


def _diagnostic_text(diagnostics: tuple[Diagnostic, ...] | list[Diagnostic]) -> str:
    if not diagnostics:
        return "Nenhum problema encontrado na leitura inicial."
    lines = []
    for diagnostic in diagnostics:
        prefix = {"error": "Erro", "warning": "Aviso", "info": "Informacao"}[diagnostic.severity]
        location = f" ({diagnostic.location})" if diagnostic.location else ""
        suggestion = f" Sugestao: {diagnostic.suggestion}" if diagnostic.suggestion else ""
        lines.append(f"{prefix}: {diagnostic.message}{location}{suggestion}")
    return "\n".join(lines)


class DropArea(QFrame):
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("dropArea")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 28)
        title = QLabel("Arraste uma planilha para esta area")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail = QLabel("Formatos aceitos: .xlsx e .csv. O arquivo permanece no computador.")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(detail)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.file_dropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return


class MappingDialog(QDialog):
    def __init__(self, result: ImportResult, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajustar interpretacao")
        self.result = result
        self.table_combo = QComboBox()
        for table in result.tables:
            self.table_combo.addItem(f"{table.source_sheet.strip()} - {table.title}", table.table_id)
        self.header_spin = QSpinBox()
        self.header_spin.setMinimum(1)
        self.header_spin.setMaximum(10000)
        self.label_spin = QSpinBox()
        self.label_spin.setMinimum(1)
        self.label_spin.setMaximum(1000)
        self.unit_edit = QLineEdit()
        self.type_combo = QComboBox()
        self.type_combo.addItem("Cobertura vacinal", "vacina")
        self.type_combo.addItem("Nascidos vivos", "nascidos")
        self.type_combo.addItem("Mortalidade", "mortalidade")
        self.type_combo.addItem("Contagem", "contagem")
        self.type_combo.addItem("Outro indicador", "desconhecido")
        form = QFormLayout()
        form.addRow("Tabela", self.table_combo)
        form.addRow("Linha do cabecalho", self.header_spin)
        form.addRow("Coluna de identificacao", self.label_spin)
        form.addRow("Unidade", self.unit_edit)
        form.addRow("Tipo do indicador", self.type_combo)
        help_text = QLabel("Use este ajuste apenas quando a deteccao automatica apontar a linha ou coluna errada.")
        help_text.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(help_text)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.table_combo.currentIndexChanged.connect(self._load_table)
        self._load_table(0)

    def _load_table(self, index: int) -> None:
        if index < 0:
            return
        table = self.result.table(self.table_combo.itemData(index))
        self.header_spin.setValue(table.header_row)
        self.label_spin.setValue(table.label_column)
        self.unit_edit.setText(table.unit)
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(table.indicator_type)))

    def values(self) -> dict[str, object]:
        return {
            "table_id": self.table_combo.currentData(),
            "header_row": self.header_spin.value(),
            "label_column": self.label_spin.value(),
            "unit": self.unit_edit.text(),
            "indicator_type": self.type_combo.currentData(),
        }


class MainWindow(QMainWindow):
    def __init__(self, service: ReportService | None = None):
        super().__init__()
        self.service = service or ReportService()
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.thread_pool = QThreadPool.globalInstance()
        self._active_worker: FunctionWorker | None = None
        self._close_requested = False
        self._artifact_cleanup_pending = False
        self._current_page = 0
        self.import_result: ImportResult | None = None
        self.current_config: ReportConfig | None = None
        self.artifact: ReportArtifact | None = None
        self.exported_pdf: Path | None = None
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(980, 700)
        self.setAcceptDrops(True)
        self._build_menu()
        self._build_ui()
        self._apply_style()

    def _build_menu(self) -> None:
        about_action = QAction("Sobre", self)
        about_action.triggered.connect(self._show_about)
        help_menu = self.menuBar().addMenu("Ajuda")
        help_menu.addAction(about_action)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(34, 26, 34, 26)
        header = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        header.addWidget(title)
        header.addStretch()
        self.step_label = QLabel("1 de 5 - Importar")
        self.step_label.setObjectName("stepLabel")
        header.addWidget(self.step_label)
        root.addLayout(header)
        self.stack = QStackedWidget()
        self.import_page = self._create_import_page()
        self.review_page = self._create_review_page()
        self.build_page = self._create_build_page()
        self.preview_page = self._create_preview_page()
        self.export_page = self._create_export_page()
        for page in (self.import_page, self.review_page, self.build_page, self.preview_page, self.export_page):
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)
        self.status_label = QLabel("Selecione uma planilha para comecar.")
        self.status_label.setObjectName("statusLabel")
        root.addWidget(self.status_label)
        self.setCentralWidget(central)

    def _nav(self, back: str = "Voltar", next_text: str = "Continuar") -> tuple[QHBoxLayout, QPushButton, QPushButton]:
        layout = QHBoxLayout()
        back_button = _button(back)
        next_button = _button(next_text, primary=True)
        layout.addWidget(back_button)
        layout.addStretch()
        layout.addWidget(next_button)
        return layout, back_button, next_button

    def _create_import_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(18)
        heading = QLabel("Importar uma planilha")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        intro = QLabel("O programa encontra tabelas anuais, preserva celulas vazias e mostra os problemas antes de gerar qualquer relatorio.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.drop_area = DropArea()
        self.drop_area.file_dropped.connect(self._inspect_file)
        layout.addWidget(self.drop_area)
        browse = _button("Procurar arquivo", primary=True)
        browse.clicked.connect(self._browse_file)
        layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignCenter)
        self.import_status = QLabel("Nenhum arquivo selecionado.")
        self.import_status.setWordWrap(True)
        layout.addWidget(self.import_status)
        layout.addStretch()
        nav, back, next_button = self._nav(next_text="Conferir dados")
        back.setEnabled(False)
        next_button.clicked.connect(lambda: self._go_to(1) if self.import_result else self._show_message("Selecione um arquivo antes de continuar."))
        layout.addLayout(nav)
        return page

    def _create_review_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel("Conferir dados reconhecidos")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        self.review_summary = QLabel("Importe um arquivo para ver as tabelas.")
        self.review_summary.setWordWrap(True)
        layout.addWidget(self.review_summary)
        self.table_widget = QTableWidget(0, 6)
        self.table_widget.setHorizontalHeaderLabels(["Usar", "Aba", "Tabela", "Anos", "Series", "Estado"])
        self.table_widget.horizontalHeader().setStretchLastSection(True)
        self.table_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table_widget, 1)
        review_actions = QHBoxLayout()
        mapping = _button("Ajustar interpretacao")
        mapping.clicked.connect(self._open_mapping)
        review_actions.addWidget(mapping)
        self.confirm_exclusions = QCheckBox("Confirmo a exclusao das tabelas com problemas")
        self.confirm_exclusions.setVisible(False)
        review_actions.addWidget(self.confirm_exclusions)
        review_actions.addStretch()
        layout.addLayout(review_actions)
        self.unrecognized_label = QLabel()
        self.unrecognized_label.setWordWrap(True)
        layout.addWidget(self.unrecognized_label)
        self.diagnostics_box = QTextEdit()
        self.diagnostics_box.setReadOnly(True)
        self.diagnostics_box.setMaximumHeight(130)
        layout.addWidget(self.diagnostics_box)
        nav, back, next_button = self._nav(next_text="Montar relatorio")
        back.clicked.connect(lambda: self._go_to(0))
        next_button.clicked.connect(self._review_next)
        layout.addLayout(nav)
        return page

    def _create_build_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel("Montar relatorio")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        self.selected_data_label = QLabel()
        self.selected_data_label.setWordWrap(True)
        layout.addWidget(self.selected_data_label)
        models = QGroupBox("Modelo de visualizacao")
        model_layout = QVBoxLayout(models)
        self.panel_radio = QRadioButton("Evolucao por macrorregiao")
        self.panel_radio.setToolTip("Um grafico pequeno para cada serie, com a mesma escala.")
        self.lines_radio = QRadioButton("Comparacao em linhas")
        self.lines_radio.setToolTip("Todas as series selecionadas no mesmo grafico.")
        self.map_radio = QRadioButton("Mapa de Santa Catarina")
        self.map_radio.setToolTip("Disponivel somente para as oito macrorregioes de saude codificadas.")
        self.panel_radio.setChecked(True)
        for radio in (self.panel_radio, self.lines_radio, self.map_radio):
            model_layout.addWidget(radio)
        self.map_help = QLabel()
        self.map_help.setWordWrap(True)
        model_layout.addWidget(self.map_help)
        layout.addWidget(models)
        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.authors_edit = QLineEdit()
        self.source_edit = QLineEdit()
        self.indicator_edit = QLineEdit()
        self.unit_edit = QLineEdit()
        form.addRow("Titulo", self.title_edit)
        form.addRow("Autores", self.authors_edit)
        form.addRow("Fonte dos dados", self.source_edit)
        form.addRow("Nome do indicador", self.indicator_edit)
        form.addRow("Unidade", self.unit_edit)
        layout.addLayout(form)
        options = QHBoxLayout()
        years_box = QGroupBox("Anos")
        self.years_layout = QHBoxLayout(years_box)
        options.addWidget(years_box, 1)
        palette_box = QGroupBox("Paleta")
        palette_layout = QVBoxLayout(palette_box)
        self.palette_combo = QComboBox()
        self.palette_combo.addItems(PALETTES)
        saved_palette = self.settings.value("palette", "Acessivel")
        if saved_palette in PALETTES:
            self.palette_combo.setCurrentText(saved_palette)
        self.palette_combo.currentTextChanged.connect(lambda value: self.settings.setValue("palette", value))
        palette_layout.addWidget(self.palette_combo)
        options.addWidget(palette_box)
        layout.addLayout(options)
        nav, back, next_button = self._nav(next_text="Gerar pre-visualizacao")
        back.clicked.connect(lambda: self._go_to(1))
        next_button.clicked.connect(self._build_next)
        layout.addStretch()
        layout.addLayout(nav)
        return page

    def _create_preview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel("Pre-visualizacao")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        body = QHBoxLayout()
        self.preview_list = QListWidget()
        self.preview_list.setMaximumWidth(250)
        self.preview_list.currentItemChanged.connect(self._show_preview_item)
        body.addWidget(self.preview_list)
        self.preview_image = QLabel("A pre-visualizacao sera exibida aqui.")
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setMinimumSize(500, 400)
        self.preview_image.setFrameShape(QFrame.Shape.StyledPanel)
        body.addWidget(self.preview_image, 1)
        layout.addLayout(body, 1)
        self.preview_progress = QProgressBar()
        self.preview_progress.setValue(0)
        layout.addWidget(self.preview_progress)
        self.cancel_preview_button = _button("Cancelar geracao")
        self.cancel_preview_button.setEnabled(False)
        self.cancel_preview_button.clicked.connect(self._cancel_worker)
        layout.addWidget(self.cancel_preview_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.preview_summary = QLabel()
        self.preview_summary.setWordWrap(True)
        layout.addWidget(self.preview_summary)
        nav, back, next_button = self._nav(next_text="Escolher destino")
        self.preview_next = next_button
        self.preview_next.setEnabled(False)
        back.clicked.connect(lambda: self._go_to(2))
        next_button.clicked.connect(lambda: self._go_to(4))
        layout.addLayout(nav)
        return page

    def _create_export_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel("Exportar PDF")
        heading.setObjectName("pageHeading")
        layout.addWidget(heading)
        self.destination_edit = QLineEdit()
        browse = _button("Escolher destino")
        browse.clicked.connect(self._browse_destination)
        destination_row = QHBoxLayout()
        destination_row.addWidget(self.destination_edit, 1)
        destination_row.addWidget(browse)
        layout.addWidget(QLabel("O arquivo sera gravado somente depois que a geracao estiver concluida."))
        layout.addLayout(destination_row)
        self.export_button = _button("Exportar PDF", primary=True)
        self.export_button.clicked.connect(self._export_pdf)
        layout.addWidget(self.export_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.export_progress = QProgressBar()
        self.export_progress.setValue(0)
        layout.addWidget(self.export_progress)
        self.cancel_export_button = _button("Cancelar exportacao")
        self.cancel_export_button.setEnabled(False)
        self.cancel_export_button.clicked.connect(self._cancel_worker)
        layout.addWidget(self.cancel_export_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.export_status = QLabel()
        self.export_status.setWordWrap(True)
        layout.addWidget(self.export_status)
        self.open_pdf_button = _button("Abrir PDF")
        self.open_folder_button = _button("Abrir pasta")
        self.open_pdf_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.open_pdf_button.clicked.connect(lambda: self._open_path(self.exported_pdf))
        self.open_folder_button.clicked.connect(lambda: self._open_path(self.exported_pdf.parent if self.exported_pdf else None))
        open_row = QHBoxLayout()
        open_row.addWidget(self.open_pdf_button)
        open_row.addWidget(self.open_folder_button)
        open_row.addStretch()
        layout.addLayout(open_row)
        layout.addStretch()
        nav, back, next_button = self._nav(next_text="Voltar ao inicio")
        back.clicked.connect(lambda: self._go_to(3))
        next_button.clicked.connect(lambda: self._go_to(0))
        layout.addLayout(nav)
        return page

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget { font-size: 13px; color: #263238; }
            QMainWindow { background: #F7F9FB; }
            #appTitle { font-size: 24px; font-weight: 700; color: #17324D; }
            #stepLabel { color: #52606D; }
            #pageHeading { font-size: 21px; font-weight: 700; color: #17324D; margin-bottom: 6px; }
            #dropArea { background: #FFFFFF; border: 2px dashed #8AB6C7; border-radius: 12px; }
            #dropTitle { font-size: 18px; font-weight: 650; color: #17324D; }
            #primaryButton { background: #176B87; color: white; border: none; border-radius: 6px; padding: 8px 18px; }
            #primaryButton:hover { background: #12566D; }
            QPushButton { padding: 7px 14px; border: 1px solid #B8C7D1; border-radius: 6px; background: #FFFFFF; }
            QPushButton:disabled { color: #9AA7AF; background: #EEF2F4; }
            QGroupBox { border: 1px solid #D7E0E5; border-radius: 8px; margin-top: 10px; padding: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #52606D; }
            QLineEdit, QTextEdit, QComboBox, QSpinBox, QTableWidget, QListWidget { background: #FFFFFF; border: 1px solid #C7D3DA; border-radius: 5px; padding: 5px; }
            #statusLabel { color: #52606D; padding-top: 4px; }
            """
        )

    def _show_about(self) -> None:
        QMessageBox.about(self, f"Sobre {APP_NAME}", f"{APP_NAME}\nVersao {APP_VERSION}\n\nProcessamento local para planilhas e relatorios de Santa Catarina.")

    def _show_message(self, message: str, title: str = "Conferencia") -> None:
        QMessageBox.warning(self, title, message)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar planilha", "", "Planilhas (*.xlsx *.csv)")
        if path:
            self._inspect_file(path)

    def _inspect_file(self, path: str) -> None:
        if self._active_worker:
            self.status_label.setText("Aguarde a operacao atual terminar ou cancele-a antes de importar outro arquivo.")
            return
        self._clear_artifact()
        self.import_status.setText(f"Lendo {Path(path).name}...")
        self.status_label.setText("Inspecionando a planilha em segundo plano.")
        self._run_worker(lambda progress, cancel: self.service.inspect(path), self._inspection_ready, self._operation_error)

    def _inspection_ready(self, result: ImportResult) -> None:
        self.import_result = result
        self.import_status.setText(f"Arquivo lido: {result.source_path.name}. {len(result.tables)} tabela(s) candidata(s) em {len(result.sheets)} aba(s).")
        self._populate_review()
        self._go_to(1, allow_active=True)

    def _populate_review(self) -> None:
        if not self.import_result:
            return
        result = self.import_result
        self.table_widget.setRowCount(0)
        invalid_ids = []
        for table in result.tables:
            row = self.table_widget.rowCount()
            self.table_widget.insertRow(row)
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            checkbox_item.setCheckState(Qt.CheckState.Checked if table.valid else Qt.CheckState.Unchecked)
            checkbox_item.setData(Qt.ItemDataRole.UserRole, table.table_id)
            self.table_widget.setItem(row, 0, checkbox_item)
            self.table_widget.setItem(row, 1, QTableWidgetItem(table.source_sheet.strip()))
            self.table_widget.setItem(row, 2, QTableWidgetItem(table.title))
            self.table_widget.setItem(row, 3, QTableWidgetItem(f"{table.years[0]} - {table.years[-1]} ({len(table.years)})" if table.years else "-"))
            self.table_widget.setItem(row, 4, QTableWidgetItem(str(len(table.series))))
            state = "Pronta" if table.valid else "Requer ajuste"
            if table.map_ready:
                state += " | mapa"
            self.table_widget.setItem(row, 5, QTableWidgetItem(state))
            if not table.valid:
                invalid_ids.append(table.table_id)
        self.confirm_exclusions.setVisible(bool(invalid_ids))
        self.confirm_exclusions.setChecked(not invalid_ids)
        unrecognized = [summary.name.strip() for summary in result.sheet_summaries if summary.status == "nao reconhecida"]
        self.unrecognized_label.setText("Abas nao reconhecidas: " + ", ".join(unrecognized) if unrecognized else "Todas as abas possuem pelo menos uma tabela candidata.")
        all_diagnostics = list(result.diagnostics) + [diagnostic for table in result.tables for diagnostic in table.diagnostics]
        self.diagnostics_box.setPlainText(_diagnostic_text(all_diagnostics))
        self.review_summary.setText(f"Foram encontradas {len(result.tables)} tabela(s). Marque o que deve entrar no PDF. Valores vazios continuam ausentes e nao viram zero.")

    def _open_mapping(self) -> None:
        if self._active_worker:
            self.status_label.setText("Aguarde a operacao atual terminar antes de ajustar a interpretacao.")
            return
        if not self.import_result:
            return
        dialog = MappingDialog(self.import_result, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            self.import_result = self.service.remap(self.import_result, values["table_id"], header_row=values["header_row"], label_column=values["label_column"], unit=values["unit"], indicator_type=values["indicator_type"])
        except Exception as error:  # noqa: BLE001 - mensagem de campo
            self._show_message(str(error), "Nao foi possivel ajustar a tabela")
            return
        self._populate_review()

    def _selected_table_ids(self) -> tuple[str, ...]:
        ids = []
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        return tuple(ids)

    def _review_next(self) -> None:
        if self._active_worker:
            self.status_label.setText("Aguarde a operacao atual terminar ou cancele-a antes de mudar de etapa.")
            return
        if not self.import_result:
            self._show_message("Importe um arquivo antes de continuar.")
            return
        selected = self._selected_table_ids()
        if not selected:
            self._show_message("Selecione pelo menos uma tabela valida.")
            return
        if self.confirm_exclusions.isVisible() and not self.confirm_exclusions.isChecked():
            self._show_message("Confirme a exclusao das tabelas que ainda possuem problemas.")
            return
        self._refresh_build_page(selected)
        self._go_to(2)

    def _refresh_build_page(self, selected: tuple[str, ...]) -> None:
        if not self.import_result:
            return
        tables = [self.import_result.table(table_id) for table_id in selected]
        common_years = sorted(set(tables[0].years).intersection(*(set(table.years) for table in tables[1:])))
        self.selected_data_label.setText(f"{len(tables)} tabela(s) selecionada(s): " + ", ".join(table.title for table in tables))
        self.title_edit.setText(self.title_edit.text() or f"Relatorio de {tables[0].title}")
        self.indicator_edit.setText(self.indicator_edit.text() or tables[0].title)
        self.unit_edit.setText(self.unit_edit.text() or tables[0].unit)
        while self.years_layout.count():
            item = self.years_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.year_checks: list[QCheckBox] = []
        for year in common_years:
            checkbox = QCheckBox(str(year))
            checkbox.setChecked(True)
            self.years_layout.addWidget(checkbox)
            self.year_checks.append(checkbox)
        self.years_layout.addStretch()
        map_available = len(tables) == 1 and tables[0].map_ready
        self.map_radio.setEnabled(map_available)
        if map_available:
            count = len(tables[0].series)
            self.map_help.setText(f"Mapa disponivel: {count} de 8 macrorregioes identificadas. Areas sem valor ficam cinzas.")
        elif len(tables) == 1 and not tables[0].valid:
            self.map_help.setText("Mapa desabilitado: corrija os problemas da tabela antes de usa-la.")
        else:
            self.map_help.setText("Mapa desabilitado: selecione uma tabela valida de cobertura com codigos reais de macrorregioes de SC. Regioes ausentes aparecem sem dados.")
        if not map_available and self.map_radio.isChecked():
            self.panel_radio.setChecked(True)

    def _build_config(self) -> ReportConfig:
        years = tuple(int(check.text()) for check in getattr(self, "year_checks", []) if check.isChecked())
        model = "mapa" if self.map_radio.isChecked() else "linhas" if self.lines_radio.isChecked() else "paineis"
        selected = self._selected_table_ids()
        excluded = tuple(table.table_id for table in self.import_result.tables if not table.valid and table.table_id not in selected) if self.import_result else ()
        return ReportConfig(selected, model, years, self.title_edit.text(), self.authors_edit.text(), self.source_edit.text(), self.indicator_edit.text(), self.unit_edit.text(), self.palette_combo.currentText(), excluded)

    def _build_next(self) -> None:
        if self._active_worker:
            self.status_label.setText("Aguarde a operacao atual terminar ou cancele-a antes de gerar a pre-visualizacao.")
            return
        if not self.import_result:
            return
        config = self._build_config()
        diagnostics = self.service.validate(self.import_result, config)
        errors = [diagnostic for diagnostic in diagnostics if diagnostic.severity == "error"]
        if errors:
            self._show_message(_diagnostic_text(errors), "Revise a configuracao")
            return
        self.current_config = config
        self._clear_artifact()
        self._go_to(3)

    def _start_preview(self) -> None:
        if not self.import_result or not self.current_config:
            return
        self.preview_next.setEnabled(False)
        self.cancel_preview_button.setEnabled(True)
        self.preview_list.clear()
        self.preview_image.setText("Gerando pre-visualizacao...")
        self.preview_progress.setValue(0)
        self._run_worker(
            lambda progress, cancel: self.service.preview(self.import_result, self.current_config, progress=progress, cancel_event=cancel),
            self._preview_ready,
            self._operation_error,
            progress_target=self.preview_progress,
        )

    def _preview_ready(self, artifact: ReportArtifact) -> None:
        self.artifact = artifact
        for image in artifact.preview_images:
            item = QListWidgetItem(image.name)
            item.setData(Qt.ItemDataRole.UserRole, str(image))
            self.preview_list.addItem(item)
        if self.preview_list.count():
            self.preview_list.setCurrentRow(0)
        self.preview_summary.setText(f"Pre-visualizacao pronta com {artifact.page_count} pagina(s). Confira a legibilidade antes de exportar.")
        self.preview_next.setEnabled(True)

    def _show_preview_item(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if not current:
            return
        path = Path(current.data(Qt.ItemDataRole.UserRole))
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self.preview_image.setPixmap(pixmap.scaled(self.preview_image.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _browse_destination(self) -> None:
        if not self.import_result:
            return
        default = str(default_export_path(self.import_result))
        path, _ = QFileDialog.getSaveFileName(self, "Salvar relatorio", default, "PDF (*.pdf)")
        if path:
            self.destination_edit.setText(path)

    def _prepare_export(self) -> None:
        if self.import_result and not self.destination_edit.text():
            self.destination_edit.setText(str(default_export_path(self.import_result)))
        self.export_status.setText("Escolha o destino e exporte o PDF quando estiver satisfeito com a pre-visualizacao.")
        self.export_button.setEnabled(bool(self.artifact))

    def _export_pdf(self) -> None:
        if self._active_worker:
            self.status_label.setText("Aguarde a operacao atual terminar ou cancele-a antes de exportar.")
            return
        if not self.artifact:
            return
        raw_destination = self.destination_edit.text().strip()
        if not raw_destination:
            self._show_message("Informe o nome e a pasta do arquivo PDF.", "Destino necessario")
            return
        target = Path(raw_destination).expanduser()
        if target.exists() and target.is_dir():
            self._show_message("O destino escolhido e uma pasta. Informe o nome do arquivo PDF.", "Destino invalido")
            return
        if not target.suffix:
            target = target.with_suffix(".pdf")
            self.destination_edit.setText(str(target))
        overwrite = False
        if target.exists():
            answer = QMessageBox.question(self, "Substituir arquivo?", f"O arquivo ja existe:\n{target}\n\nDeseja substitui-lo?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        self.export_button.setEnabled(False)
        self.cancel_export_button.setEnabled(True)
        self.export_progress.setValue(0)
        self._run_worker(lambda progress, cancel: self.service.export(self.artifact, target, overwrite=overwrite, progress=progress, cancel_event=cancel), self._export_ready, self._operation_error, progress_target=self.export_progress)

    def _export_ready(self, path: Path) -> None:
        self.exported_pdf = path
        self.settings.setValue("last_export_dir", str(path.parent))
        self.export_status.setText(f"PDF exportado com sucesso:\n{path}")
        self.open_pdf_button.setEnabled(True)
        self.open_folder_button.setEnabled(True)
        self.export_button.setEnabled(True)

    def _open_path(self, path: Path | None) -> None:
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _run_worker(self, function, on_result, on_error, progress_target: QProgressBar | None = None) -> None:
        if self._active_worker:
            self.status_label.setText("Ja existe uma operacao em andamento. Aguarde a conclusao ou cancele-a.")
            return
        worker = FunctionWorker(function)
        self._active_worker = worker
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        worker.signals.progress.connect(lambda value, message: self._worker_progress(value, message, progress_target))
        worker.signals.finished.connect(self._worker_finished)
        self.thread_pool.start(worker)

    def _worker_progress(self, value: int, message: str, target: QProgressBar | None) -> None:
        self.status_label.setText(message)
        if target:
            target.setValue(value)

    def _worker_finished(self) -> None:
        self._active_worker = None
        self.cancel_preview_button.setEnabled(False)
        self.cancel_export_button.setEnabled(False)
        self.export_button.setEnabled(bool(self.artifact))
        if self._artifact_cleanup_pending or self._close_requested:
            QTimer.singleShot(0, self._finish_deferred_cleanup)

    def _finish_deferred_cleanup(self) -> None:
        if self._artifact_cleanup_pending:
            self._artifact_cleanup_pending = False
            self._clear_artifact()
        if self._close_requested:
            self._close_requested = False
            self._clear_artifact()
            self.close()

    def _cancel_worker(self) -> None:
        if self._active_worker:
            self._active_worker.cancel_event.set()
            self.status_label.setText("Cancelando a operacao...")

    def _operation_error(self, error: BaseException) -> None:
        if isinstance(error, (OperationCancelled, RenderCancelled)):
            self.status_label.setText("Operacao cancelada.")
            return
        if isinstance(error, ReportValidationError):
            message = _diagnostic_text(error.diagnostics)
        else:
            message = str(error)
        self.status_label.setText("A operacao nao foi concluida.")
        self._show_message(message, "Nao foi possivel concluir")

    def _clear_artifact(self) -> None:
        if self._active_worker:
            self._artifact_cleanup_pending = True
            self.status_label.setText("A pre-visualizacao sera removida quando a operacao atual terminar.")
            return
        if self.artifact:
            self.service.cleanup(self.artifact)
        self.artifact = None
        self.exported_pdf = None
        self.open_pdf_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.current_config = None if self._current_page <= 1 else self.current_config

    def _go_to(self, index: int, *, allow_active: bool = False) -> None:
        if index < 0 or index > 4:
            return
        if self._active_worker and not allow_active:
            self.status_label.setText("Aguarde a operacao atual terminar ou cancele-a antes de mudar de etapa.")
            return
        self._current_page = index
        self.stack.setCurrentIndex(index)
        labels = ["Importar", "Conferir dados", "Montar relatorio", "Pre-visualizacao", "Exportar"]
        self.step_label.setText(f"{index + 1} de 5 - {labels[index]}")
        if index == 3:
            self._start_preview()
        elif index == 4:
            self._prepare_export()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self._inspect_file(url.toLocalFile())
                event.acceptProposedAction()
                return

    def closeEvent(self, event) -> None:  # noqa: N802 - assinatura Qt
        if self._active_worker:
            self._close_requested = True
            self._active_worker.cancel_event.set()
            self.status_label.setText("Cancelando a operacao antes de fechar...")
            event.ignore()
            return
        if self._artifact_cleanup_pending or self._close_requested:
            event.ignore()
            return
        self._clear_artifact()
        super().closeEvent(event)


def run_app() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    window = MainWindow()
    window.show()
    return app.exec()
