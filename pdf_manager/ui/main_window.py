"""Main PySide6 window for the PDF Manager app."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pdf_manager.core.config import AppConfig
from pdf_manager.core.export_excel import export_records_to_excel
from pdf_manager.core.pdf_text import extract_pdf_text
from pdf_manager.core.prompts import DEFAULT_EXTRACTION_PROMPT, render_prompt
from pdf_manager.core.scanner import PdfScanner
from pdf_manager.integrations.docling_adapter import DoclingAdapter, is_docling_available
from pdf_manager.integrations.ollama_client import OllamaClient
from pdf_manager.models.pdf_record import PdfRecord
from pdf_manager.ui.distribution_chart import DistributionChartWidget
from pdf_manager.ui.table_model import DEFAULT_COLUMNS, PdfFilterProxyModel, PdfTableModel

LOGGER = logging.getLogger(__name__)
WHOLE_MACHINE_ROOT = "/"
MAX_PROMPT_FILES = 0  # 0 means no explicit selection limit for Ollama extraction


class ScanWorker(QObject):
    """Runs PDF scanning on a background Qt thread."""

    record_found = Signal(object)
    progress = Signal(int, int, str)
    discovering = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, folders: list[str], stop_event: Event) -> None:
        super().__init__()
        self.folders = folders
        self.stop_event = stop_event

    @Slot()
    def run(self) -> None:
        scanner = PdfScanner(include_text_preview=True)
        try:
            scanner.scan(
                self.folders,
                stop_event=self.stop_event,
                progress_callback=lambda current, total, path: self.progress.emit(current, total, str(path)),
                record_callback=lambda record: self.record_found.emit(record),
                discovery_callback=lambda path: self.discovering.emit(str(path)),
            )
        except Exception as exc:
            LOGGER.exception("Scan failed")
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class OllamaExtractionWorker(QObject):
    """Runs local Ollama extraction outside the GUI thread."""

    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        records: list[PdfRecord],
        model: str,
        base_url: str,
        timeout_seconds: int,
        options: dict[str, float | int],
        extraction_backend: str,
        prompt_template: str,
        stop_event: Event,
    ) -> None:
        super().__init__()
        self.records = records
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.options = options
        self.extraction_backend = extraction_backend
        self.prompt_template = prompt_template
        self.stop_event = stop_event

    @Slot()
    def run(self) -> None:
        try:
            client = OllamaClient(base_url=self.base_url, timeout_seconds=self.timeout_seconds)
            result_rows: list[dict[str, str]] = []
            total = len(self.records)
            for current, record in enumerate(self.records, start=1):
                if self.stop_event.is_set():
                    break
                self.progress.emit(current, total, record.file_name)
                try:
                    text = self._extract_text(record.full_path)
                    if self.stop_event.is_set():
                        break
                    if not text.strip():
                        result_rows.append(_extraction_result_row(record, "error", "No extractable text found in PDF"))
                        continue
                    prompt = render_prompt(self.prompt_template, record, text)
                    result = client.generate(prompt=prompt, model=self.model, options=self.options)
                    result_rows.append(_extraction_result_row(record, "complete", result or "Ollama returned an empty response."))
                except Exception as exc:
                    LOGGER.exception("Ollama extraction failed for %s", record.full_path)
                    result_rows.append(_extraction_result_row(record, "error", str(exc)))
            self.finished.emit(result_rows)
        except Exception as exc:
            LOGGER.exception("Ollama extraction failed")
            self.failed.emit(str(exc))

    def _extract_text(self, path: str) -> str:
        if self.extraction_backend == "docling":
            return DoclingAdapter().extract_text(path)
        return extract_pdf_text(path)


def _extraction_result_row(record: PdfRecord, status: str, result: str) -> dict[str, str]:
    return {
        "file_name": record.file_name,
        "full_path": record.full_path,
        "status": status,
        "result": result,
    }


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.selected_folders = config.last_selected_folders.copy()
        self.current_scan_roots = self.selected_folders.copy()
        self.stop_event = Event()
        self.scan_thread: QThread | None = None
        self.scan_worker: ScanWorker | None = None
        self.ollama_thread: QThread | None = None
        self.ollama_worker: OllamaExtractionWorker | None = None
        self.ollama_stop_event: Event | None = None
        self.ollama_timer = QTimer(self)
        self.ollama_timer.timeout.connect(self._ollama_timer_tick)
        self.ollama_timer.setInterval(500)
        self.ollama_start_time: float | None = None
        self.ollama_last_progress_text = ""
        self.latest_extraction_pdf_path = ""

        self.model = PdfTableModel(config.visible_columns or DEFAULT_COLUMNS.copy())
        self.proxy = PdfFilterProxyModel()
        self.proxy.setSourceModel(self.model)

        self.setWindowTitle("PDF Manager")
        self.resize(1280, 720)
        self._build_ui()
        self._update_folder_label()
        self._update_folder_filter_options()

    def _button(self, text: str, icon: QStyle.StandardPixmap) -> QPushButton:
        button = QPushButton(text)
        button.setIcon(self.style().standardIcon(icon))
        button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        return button

    def _section_header(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #111111; font-size: 14px; font-weight: 700;")
        return label

    def _app_header(self) -> QLabel:
        label = QLabel("PDF Manager - Python desktop app")
        label.setStyleSheet("color: #0f172a; font-size: 18px; font-weight: 800;")
        return label

    def _build_ui(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        choose_button = self._button("Add Folder", QStyle.SP_DirOpenIcon)
        choose_button.setToolTip("Add a folder to scan for PDFs")
        choose_button.clicked.connect(self.choose_folders)
        toolbar.addWidget(choose_button)

        self.start_button = self._button("Start Scan", QStyle.SP_MediaPlay)
        self.start_button.setToolTip("Scan the selected folders")
        self.start_button.clicked.connect(self.start_scan)
        toolbar.addWidget(self.start_button)

        self.scan_all_button = self._button("Scan All", QStyle.SP_DriveHDIcon)
        self.scan_all_button.setToolTip("Scan the entire machine")
        self.scan_all_button.clicked.connect(self.start_entire_machine_scan)
        toolbar.addWidget(self.scan_all_button)

        self.stop_button = self._button("Stop", QStyle.SP_MediaStop)
        self.stop_button.setToolTip("Stop the current scan")
        self.stop_button.clicked.connect(self.stop_scan)
        self.stop_button.setEnabled(False)
        toolbar.addWidget(self.stop_button)

        refresh_button = self._button("Refresh", QStyle.SP_BrowserReload)
        refresh_button.setToolTip("Run the last scan again")
        refresh_button.clicked.connect(self.refresh_scan)
        toolbar.addWidget(refresh_button)

        export_button = self._button("Export", QStyle.SP_DialogSaveButton)
        export_button.setToolTip("Export the visible PDF list to Excel")
        export_button.clicked.connect(self.export_current_view)
        toolbar.addWidget(export_button)

        open_button = self._button("Open PDF", QStyle.SP_FileIcon)
        open_button.setToolTip("Open the selected PDF")
        open_button.clicked.connect(self.open_selected_pdf)
        toolbar.addWidget(open_button)

        reveal_button = self._button("Finder", QStyle.SP_DirIcon)
        reveal_button.setToolTip("Show the selected PDF in Finder")
        reveal_button.clicked.connect(self.reveal_selected_pdf)
        toolbar.addWidget(reveal_button)

        central = QWidget()
        central.setStyleSheet("""
            QWidget {
                background-color: #f8fafc;
            }
            QToolBar {
                background: transparent;
                spacing: 6px;
                padding: 4px 0;
            }
            QPushButton {
                background-color: #1d4ed8;
                color: white;
                border: 1px solid #1e40af;
                border-radius: 7px;
                padding: 7px 10px;
                min-height: 32px;
                font-weight: 700;
                text-transform: none;
            }
            QPushButton:hover:enabled {
                background-color: #1e40af;
            }
            QPushButton:pressed:enabled {
                background-color: #1e3a8a;
            }
            QPushButton:disabled {
                background-color: #64748b;
                color: #f8fafc;
                border-color: #475569;
            }
            QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #f4f6fb;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 7px;
                padding: 8px 10px;
                min-height: 30px;
            }
            QPlainTextEdit {
                background-color: #ffffff;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border: 1px solid #2563eb;
                background-color: #ffffff;
            }
            QComboBox {
                padding-right: 24px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border-left: 1px solid #cbd5e1;
            }
            QTableWidget, QTableView {
                background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #d1d5db;
                gridline-color: #e5e7eb;
            }
            QTableView::item:selected, QTableWidget::item:selected {
                background-color: #dbeafe;
                color: #1e3a8a;
            }
            QHeaderView::section {
                background-color: #e2e8f0;
                border: 1px solid #cbd5e1;
                padding: 6px 8px;
                font-weight: 700;
                color: #0f172a;
            }
            QLabel {
                color: #0f172a;
                font-weight: 600;
            }
        """)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        self.app_title_label = self._app_header()
        main_layout.addWidget(self.app_title_label)

        self.folder_label = QLabel()
        self.scan_summary_label = QLabel()
        self.scan_summary_label.setWordWrap(True)

        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.setChildrenCollapsible(False)
        top_splitter.setOpaqueResize(True)
        top_splitter.setHandleWidth(10)

        chart_panel = QWidget()
        chart_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        chart_panel.setMinimumWidth(220)
        chart_panel.setStyleSheet(
            "background-color: #eff6ff; color: #111111; border: 1px solid #dbeafe; border-radius: 10px;"
        )
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(10, 10, 10, 10)
        chart_layout.setSpacing(10)
        chart_header = QLabel("Charts")
        chart_header.setStyleSheet("color: #111111; font-size: 12px; font-weight: 700;")
        chart_layout.addWidget(chart_header)
        self.distribution_chart = DistributionChartWidget()
        self.distribution_chart.setMinimumHeight(140)
        chart_layout.addWidget(self.distribution_chart)
        chart_scroll = QScrollArea()
        chart_scroll.setWidgetResizable(True)
        chart_scroll.setFrameShape(QScrollArea.NoFrame)
        chart_scroll.setWidget(chart_panel)
        top_splitter.addWidget(chart_scroll)

        config_panel = QWidget()
        config_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        config_panel.setMinimumWidth(260)
        config_panel.setStyleSheet(
            "background-color: #ecfdf5; color: #111111; border: 1px solid #bbf7d0; border-radius: 10px;"
        )
        config_layout = QVBoxLayout(config_panel)
        config_layout.setContentsMargins(10, 10, 10, 10)
        config_layout.setSpacing(10)
        config_header = self._section_header("Configuration")
        config_layout.addWidget(config_header)
        config_layout.addWidget(self.folder_label)
        config_layout.addWidget(self.scan_summary_label)

        folder_manage_row = QHBoxLayout()
        self.selected_folder_input = QComboBox()
        self.selected_folder_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.selected_folder_input.setToolTip("Selected folders used by Start Scan")
        self.add_folder_button = self._button("Add", QStyle.SP_DirOpenIcon)
        self.add_folder_button.setToolTip("Add a folder to scan")
        self.add_folder_button.clicked.connect(self.choose_folders)
        self.remove_folder_button = self._button("Remove", QStyle.SP_TrashIcon)
        self.remove_folder_button.setToolTip("Remove the selected folder from the scan list")
        self.remove_folder_button.clicked.connect(self.remove_selected_folder)
        folder_manage_row.addWidget(self.selected_folder_input, 1)
        folder_manage_row.addWidget(self.add_folder_button)
        folder_manage_row.addWidget(self.remove_folder_button)
        config_layout.addLayout(folder_manage_row)

        self.refresh_section_button = self._button("Refresh", QStyle.SP_BrowserReload)
        self.refresh_section_button.setToolTip("Run the last scan again")
        self.refresh_section_button.clicked.connect(self.refresh_scan)
        config_layout.addWidget(self.refresh_section_button)

        filter_layout = QFormLayout()
        filter_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        filter_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search file name, path, metadata, preview, or errors")
        self.search_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.search_input.textChanged.connect(self.proxy.set_search_text)
        self.search_input.textChanged.connect(lambda _: self._update_scan_summary())
        filter_layout.addRow("Search", self.search_input)

        self.folder_filter = QComboBox()
        self.folder_filter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.folder_filter.currentTextChanged.connect(self._folder_filter_changed)
        filter_layout.addRow("Folder", self.folder_filter)

        page_range = QHBoxLayout()
        self.min_pages = QSpinBox()
        self.min_pages.setRange(0, 1_000_000)
        self.min_pages.setSpecialValueText("Any")
        self.min_pages.valueChanged.connect(self._page_filter_changed)
        self.max_pages = QSpinBox()
        self.max_pages.setRange(0, 1_000_000)
        self.max_pages.setSpecialValueText("Any")
        self.max_pages.valueChanged.connect(self._page_filter_changed)
        page_range.addWidget(self.min_pages)
        page_range.addWidget(QLabel("to"))
        page_range.addWidget(self.max_pages)
        page_range.setStretch(0, 1)
        page_range.setStretch(2, 1)
        filter_layout.addRow("Pages", page_range)

        size_range = QHBoxLayout()
        self.min_size = QDoubleSpinBox()
        self.min_size.setRange(0, 1_000_000)
        self.min_size.setDecimals(2)
        self.min_size.setSpecialValueText("Any")
        self.min_size.valueChanged.connect(self._size_filter_changed)
        self.max_size = QDoubleSpinBox()
        self.max_size.setRange(0, 1_000_000)
        self.max_size.setDecimals(2)
        self.max_size.setSpecialValueText("Any")
        self.max_size.valueChanged.connect(self._size_filter_changed)
        size_range.addWidget(self.min_size)
        size_range.addWidget(QLabel("to MiB"))
        size_range.addWidget(self.max_size)
        size_range.setStretch(0, 1)
        size_range.setStretch(2, 1)
        filter_layout.addRow("Size", size_range)

        self.encrypted_filter = QComboBox()
        self.encrypted_filter.addItems(["Any", "Encrypted", "Not encrypted"])
        self.encrypted_filter.currentIndexChanged.connect(self._encrypted_filter_changed)
        filter_layout.addRow("Encryption", self.encrypted_filter)

        self.text_filter = QComboBox()
        self.text_filter.addItems(["Any", "Text extractable", "Not text extractable"])
        self.text_filter.currentIndexChanged.connect(self._text_filter_changed)
        filter_layout.addRow("Text", self.text_filter)

        config_layout.addLayout(filter_layout)
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setFrameShape(QScrollArea.NoFrame)
        config_scroll.setWidget(config_panel)
        top_splitter.addWidget(config_scroll)

        llm_panel = QWidget()
        llm_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        llm_panel.setMinimumWidth(260)
        llm_panel.setStyleSheet(
            "background-color: #fffbeb; color: #111111; border: 1px solid #fde68a; border-radius: 10px;"
        )
        llm_layout = QVBoxLayout(llm_panel)
        llm_layout.setContentsMargins(10, 10, 10, 10)
        llm_layout.setSpacing(10)
        llm_header = self._section_header("LLM results")
        llm_layout.addWidget(llm_header)

        ollama_layout = QFormLayout()
        ollama_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        ollama_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.ollama_base_url_input = QLineEdit(self.config.ollama_base_url)
        self.ollama_base_url_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        ollama_layout.addRow("Ollama URL", self.ollama_base_url_input)

        model_row = QHBoxLayout()
        self.ollama_model_input = QLineEdit(self.config.ollama_model)
        self.ollama_model_input.setPlaceholderText("example: llama3.1:8b")
        self.ollama_model_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_models_button = self._button("Models", QStyle.SP_BrowserReload)
        self.refresh_models_button.setToolTip("Load local Ollama models")
        self.refresh_models_button.clicked.connect(self.refresh_ollama_models)
        model_row.addWidget(self.ollama_model_input)
        model_row.addWidget(self.refresh_models_button)
        model_row.setStretch(0, 1)
        ollama_layout.addRow("Ollama Model", model_row)

        generation_row = QHBoxLayout()
        self.ollama_temperature_input = QDoubleSpinBox()
        self.ollama_temperature_input.setRange(0.0, 2.0)
        self.ollama_temperature_input.setDecimals(2)
        self.ollama_temperature_input.setSingleStep(0.05)
        self.ollama_temperature_input.setValue(self.config.ollama_temperature)
        self.ollama_temperature_input.setToolTip("Lower values are more focused. Higher values are more creative.")
        self.ollama_top_p_input = QDoubleSpinBox()
        self.ollama_top_p_input.setRange(0.0, 1.0)
        self.ollama_top_p_input.setDecimals(2)
        self.ollama_top_p_input.setSingleStep(0.05)
        self.ollama_top_p_input.setValue(self.config.ollama_top_p)
        self.ollama_top_p_input.setToolTip("Limits token choices by probability mass.")
        generation_row.addWidget(QLabel("Temp"))
        generation_row.addWidget(self.ollama_temperature_input)
        generation_row.addWidget(QLabel("Top-p"))
        generation_row.addWidget(self.ollama_top_p_input)
        generation_row.setStretch(1, 1)
        generation_row.setStretch(3, 1)
        ollama_layout.addRow("Generation", generation_row)

        limits_row = QHBoxLayout()
        self.ollama_top_k_input = QSpinBox()
        self.ollama_top_k_input.setRange(0, 10_000)
        self.ollama_top_k_input.setSpecialValueText("Auto")
        self.ollama_top_k_input.setValue(self.config.ollama_top_k)
        self.ollama_top_k_input.setToolTip("Limits token choices to the best ranked options. Auto lets Ollama decide.")
        self.ollama_num_predict_input = QSpinBox()
        self.ollama_num_predict_input.setRange(0, 100_000)
        self.ollama_num_predict_input.setSpecialValueText("Auto")
        self.ollama_num_predict_input.setValue(self.config.ollama_num_predict)
        self.ollama_num_predict_input.setToolTip("Maximum generated tokens. Auto lets Ollama decide.")
        limits_row.addWidget(QLabel("Top-k"))
        limits_row.addWidget(self.ollama_top_k_input)
        limits_row.addWidget(QLabel("Max tokens"))
        limits_row.addWidget(self.ollama_num_predict_input)
        limits_row.setStretch(1, 1)
        limits_row.setStretch(3, 1)
        ollama_layout.addRow("Limits", limits_row)

        runtime_row = QHBoxLayout()
        self.ollama_num_ctx_input = QSpinBox()
        self.ollama_num_ctx_input.setRange(0, 1_000_000)
        self.ollama_num_ctx_input.setSpecialValueText("Auto")
        self.ollama_num_ctx_input.setValue(self.config.ollama_num_ctx)
        self.ollama_num_ctx_input.setToolTip("Context window size. Auto lets Ollama decide.")
        self.ollama_timeout_input = QSpinBox()
        self.ollama_timeout_input.setRange(5, 3_600)
        self.ollama_timeout_input.setSuffix(" sec")
        self.ollama_timeout_input.setValue(self.config.ollama_timeout_seconds)
        self.ollama_timeout_input.setToolTip("Maximum wait time for each Ollama request.")
        runtime_row.addWidget(QLabel("Context"))
        runtime_row.addWidget(self.ollama_num_ctx_input)
        runtime_row.addWidget(QLabel("Timeout"))
        runtime_row.addWidget(self.ollama_timeout_input)
        runtime_row.setStretch(1, 1)
        runtime_row.setStretch(3, 1)
        ollama_layout.addRow("Runtime", runtime_row)

        backend_row = QHBoxLayout()
        self.pypdf_backend_option = QRadioButton("Default pypdf")
        self.pypdf_backend_option.setToolTip("Fast built-in PDF text extraction.")
        self.docling_backend_option = QRadioButton("Docling slower")
        self.docling_backend_option.setToolTip("Structured Docling extraction. This can take more time per PDF.")
        if self.config.extraction_backend == "docling":
            self.docling_backend_option.setChecked(True)
        else:
            self.pypdf_backend_option.setChecked(True)
        self.pypdf_backend_option.toggled.connect(self._extraction_backend_changed)
        self.docling_backend_option.toggled.connect(self._extraction_backend_changed)
        backend_row.addWidget(self.pypdf_backend_option)
        backend_row.addWidget(self.docling_backend_option)
        backend_row.addStretch(1)
        ollama_layout.addRow("PDF text", backend_row)

        self.docling_warning_label = QLabel(
            "Docling can take significantly more time per PDF because it performs structured document conversion."
        )
        self.docling_warning_label.setWordWrap(True)
        self.docling_warning_label.setStyleSheet("color: #92400e; font-size: 11px;")
        self.docling_warning_label.setVisible(self._selected_extraction_backend() == "docling")
        ollama_layout.addRow("", self.docling_warning_label)

        self.docling_availability_label = QLabel()
        self.docling_availability_label.setWordWrap(True)
        self._update_docling_availability_label()
        ollama_layout.addRow("", self.docling_availability_label)

        self.prompt_input = QPlainTextEdit()
        self.prompt_input.setPlainText(self.config.extraction_prompt)
        self.prompt_input.setPlaceholderText(
            "Use placeholders such as {file_name}, {full_path}, {page_count}, {text}, and {documents}"
        )
        self.prompt_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.prompt_input.setMinimumHeight(180)
        ollama_layout.addRow(self._section_header("Extraction prompt"))

        run_prompt_row = QHBoxLayout()
        self.run_extraction_button = self._button("Run Selected", QStyle.SP_MediaPlay)
        self.run_extraction_button.setToolTip("Run the prompt for selected PDFs")
        self.run_extraction_button.clicked.connect(self.run_ollama_extraction)
        self.save_prompt_button = self._button("Save", QStyle.SP_DialogSaveButton)
        self.save_prompt_button.setToolTip("Save prompt and Ollama settings")
        self.save_prompt_button.clicked.connect(self._persist_ollama_settings)
        self.reset_prompt_button = self._button("Reset", QStyle.SP_DialogResetButton)
        self.reset_prompt_button.setToolTip("Restore the default prompt")
        self.reset_prompt_button.clicked.connect(self._reset_prompt_to_default)
        self.stop_ollama_button = self._button("Stop", QStyle.SP_MediaStop)
        self.stop_ollama_button.setToolTip("Stop local extraction")
        self.stop_ollama_button.clicked.connect(self.stop_ollama_extraction)
        self.stop_ollama_button.setEnabled(False)
        run_prompt_row.addWidget(self.run_extraction_button)
        run_prompt_row.addWidget(self.save_prompt_button)
        run_prompt_row.addWidget(self.reset_prompt_button)
        run_prompt_row.addWidget(self.stop_ollama_button)
        run_prompt_row.addStretch(1)
        ollama_layout.addRow("Local Extraction", run_prompt_row)

        self.extraction_progress_label = QLabel("No local extraction running.")
        ollama_layout.addRow("Extraction Progress", self.extraction_progress_label)

        self.extraction_elapsed_label = QLabel("0:00")
        ollama_layout.addRow("Elapsed time", self.extraction_elapsed_label)

        self.ollama_parameters_label = QLabel("Parameters: not used yet")
        self.ollama_parameters_label.setWordWrap(True)
        ollama_layout.addRow("Last settings", self.ollama_parameters_label)

        latest_pdf_row = QHBoxLayout()
        self.latest_extraction_pdf_label = QLabel("No extracted PDF available.")
        self.latest_extraction_pdf_label.setWordWrap(True)
        self.open_latest_extraction_pdf_button = self._button("Open latest PDF", QStyle.SP_FileIcon)
        self.open_latest_extraction_pdf_button.setToolTip("Open the latest PDF from the extraction results")
        self.open_latest_extraction_pdf_button.setEnabled(False)
        self.open_latest_extraction_pdf_button.clicked.connect(self.open_latest_extraction_pdf)
        latest_pdf_row.addWidget(self.latest_extraction_pdf_label, 1)
        latest_pdf_row.addWidget(self.open_latest_extraction_pdf_button)
        ollama_layout.addRow("Extracted PDF", latest_pdf_row)

        self.extraction_result_table = QTableWidget(0, 5)
        self.extraction_result_table.setHorizontalHeaderLabels(["File", "Path", "Status", "Result / Error", "Action"])
        self.extraction_result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.extraction_result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.extraction_result_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.extraction_result_table.setMinimumHeight(220)
        self.extraction_result_table.doubleClicked.connect(lambda _: self.open_selected_extraction_pdf())
        self.extraction_result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.extraction_result_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.extraction_result_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.extraction_result_table.horizontalHeader().setStretchLastSection(False)

        llm_layout.addLayout(ollama_layout)

        resize_hint = QLabel("Drag the LLM split handle to resize prompt and results.")
        resize_hint.setStyleSheet("color: #4b5563; font-size: 11px;")
        llm_layout.addWidget(resize_hint)

        result_label = self._section_header("Extraction result")
        llm_layout.addWidget(result_label)

        llm_splitter = QSplitter(Qt.Vertical)
        llm_splitter.setChildrenCollapsible(False)
        llm_splitter.setOpaqueResize(True)
        llm_splitter.setHandleWidth(8)
        llm_splitter.addWidget(self.prompt_input)
        llm_splitter.addWidget(self.extraction_result_table)
        llm_splitter.setSizes([180, 260])
        llm_layout.addWidget(llm_splitter)
        llm_scroll = QScrollArea()
        llm_scroll.setWidgetResizable(True)
        llm_scroll.setFrameShape(QScrollArea.NoFrame)
        llm_scroll.setWidget(llm_panel)
        top_splitter.addWidget(llm_scroll)
        top_splitter.setSizes([240, 280, 320])

        vertical_splitter = QSplitter(Qt.Vertical)
        vertical_splitter.setChildrenCollapsible(False)
        vertical_splitter.setOpaqueResize(True)
        vertical_splitter.setHandleWidth(10)
        vertical_splitter.addWidget(top_splitter)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.doubleClicked.connect(lambda _: self.open_selected_pdf())
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        vertical_splitter.addWidget(self.table)
        vertical_splitter.setSizes([240, 460])

        main_layout.addWidget(vertical_splitter)

        self.status = QLabel("Ready")
        main_layout.addWidget(self.status)

        self.setCentralWidget(central)

    @Slot()
    def choose_folders(self) -> None:
        dialog = QFileDialog(self, "Add a folder to scan")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        if self.selected_folders:
            dialog.setDirectory(self.selected_folders[0])
        if dialog.exec():
            folder = dialog.selectedFiles()[0]
            if folder not in self.selected_folders:
                self.selected_folders.append(folder)
            self._persist_folders()
            self._update_folder_label()
            self._update_scan_summary()

    @Slot()
    def remove_selected_folder(self) -> None:
        folder = self.selected_folder_input.currentData()
        if not folder:
            return
        self.selected_folders = [path for path in self.selected_folders if path != folder]
        if self.current_scan_roots == [folder] or folder in self.current_scan_roots:
            self.current_scan_roots = [path for path in self.current_scan_roots if path != folder]
        self._persist_folders()
        self._update_folder_label()
        self._update_scan_summary()

    @Slot()
    def start_scan(self) -> None:
        if not self.selected_folders:
            QMessageBox.information(
                self,
                "No scan scope selected",
                "Add one or more folders, or use Scan Entire Machine.",
            )
            return
        self._start_scan(self.selected_folders.copy())

    @Slot()
    def start_entire_machine_scan(self) -> None:
        if self.scan_thread is not None:
            return
        answer = QMessageBox.question(
            self,
            "Scan entire machine",
            "Scan the entire machine from /? This can take a long time and may report permission errors for protected folders.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._start_scan([WHOLE_MACHINE_ROOT])

    def _start_scan(self, roots: list[str]) -> None:
        if self.scan_thread is not None:
            return
        self.current_scan_roots = roots
        self.model.clear()
        self._update_folder_filter_options()
        self._update_folder_label()
        self._update_scan_summary()
        self.stop_event.clear()
        self.start_button.setEnabled(False)
        self.scan_all_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText("Scanning " + self._scan_scope_label() + "...")

        self.scan_thread = QThread(self)
        self.scan_worker = ScanWorker(roots, self.stop_event)
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.record_found.connect(self._record_found)
        self.scan_worker.progress.connect(self._scan_progress)
        self.scan_worker.discovering.connect(self._scan_discovering)
        self.scan_worker.failed.connect(self._scan_failed)
        self.scan_worker.finished.connect(self._scan_finished)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_worker.finished.connect(self.scan_worker.deleteLater)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_thread.finished.connect(self._thread_deleted)
        self.scan_thread.start()

    @Slot()
    def stop_scan(self) -> None:
        self.stop_event.set()
        self.status.setText("Stopping scan...")
        self.stop_button.setEnabled(False)

    @Slot()
    def refresh_scan(self) -> None:
        if self.scan_thread is not None:
            self.stop_scan()
            return
        if self.current_scan_roots:
            self._start_scan(self.current_scan_roots.copy())
            return
        self.start_scan()

    @Slot(object)
    def _record_found(self, record: PdfRecord) -> None:
        self.model.add_record(record)
        self._update_folder_filter_options()
        self._update_scan_summary()

    @Slot(int, int, str)
    def _scan_progress(self, current: int, total: int, path: str) -> None:
        self.status.setText(f"Scanned {current}/{total}: {Path(path).name}")

    @Slot(str)
    def _scan_discovering(self, path: str) -> None:
        self.status.setText(f"Searching {path}")

    @Slot(str)
    def _scan_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Scan failed", message)

    @Slot()
    def _scan_finished(self) -> None:
        self.start_button.setEnabled(True)
        self.scan_all_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status.setText(f"Ready - {self.proxy.rowCount()} visible of {self.model.rowCount()} scanned")
        self._update_scan_summary()

    @Slot()
    def _thread_deleted(self) -> None:
        self.scan_thread = None
        self.scan_worker = None

    def _selected_record(self) -> PdfRecord | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        source_index = self.proxy.mapToSource(indexes[0])
        return self.model.record_at(source_index.row())

    def _selected_records(self) -> list[PdfRecord]:
        records: list[PdfRecord] = []
        seen_paths: set[str] = set()
        for index in self.table.selectionModel().selectedRows():
            source_index = self.proxy.mapToSource(index)
            record = self.model.record_at(source_index.row())
            if record is not None and record.full_path not in seen_paths:
                records.append(record)
                seen_paths.add(record.full_path)
        return records

    @Slot()
    def open_selected_pdf(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        self._open_pdf_path(record.full_path)

    @Slot()
    def reveal_selected_pdf(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        subprocess.run(["open", "-R", record.full_path], check=False)

    @Slot()
    def open_selected_extraction_pdf(self) -> None:
        path = self._selected_extraction_pdf_path()
        if path:
            self._open_pdf_path(path)

    @Slot()
    def open_latest_extraction_pdf(self) -> None:
        if self.latest_extraction_pdf_path:
            self._open_pdf_path(self.latest_extraction_pdf_path)

    def _selected_extraction_pdf_path(self) -> str:
        indexes = self.extraction_result_table.selectionModel().selectedRows()
        if not indexes:
            return ""
        item = self.extraction_result_table.item(indexes[0].row(), 1)
        return item.text() if item is not None else ""

    def _open_pdf_path(self, path: str) -> None:
        if not path:
            return
        subprocess.run(["open", path], check=False)

    @Slot()
    def export_current_view(self) -> None:
        start_dir = self.config.last_export_location or str(Path.home())
        output, _ = QFileDialog.getSaveFileName(self, "Export PDF table", start_dir, "Excel Workbook (*.xlsx)")
        if not output:
            return
        if not output.lower().endswith(".xlsx"):
            output += ".xlsx"
        records = self._visible_records()
        try:
            export_records_to_excel(records, output, self.model.columns, self.current_scan_roots)
            self.config.last_export_location = str(Path(output).parent)
            self.config.visible_columns = self.model.columns.copy()
            self.config.save()
            self.status.setText(f"Exported {len(records)} records to {output}")
        except Exception as exc:
            LOGGER.exception("Export failed")
            QMessageBox.warning(self, "Export failed", str(exc))

    @Slot()
    def refresh_ollama_models(self) -> None:
        self._persist_ollama_settings()
        try:
            models = OllamaClient(base_url=self.config.ollama_base_url, timeout_seconds=10).list_models()
        except Exception as exc:
            QMessageBox.warning(self, "Ollama unavailable", str(exc))
            return
        if not models:
            QMessageBox.information(self, "No local Ollama models", "Ollama is reachable, but no local models were listed.")
            return
        self.ollama_model_input.setText(models[0])
        self.status.setText("Loaded Ollama models: " + ", ".join(models[:5]))

    @Slot()
    def run_ollama_extraction(self) -> None:
        records = self._selected_records()
        if not records:
            QMessageBox.information(self, "No PDF selected", "Select one or more PDF rows first.")
            return
        if MAX_PROMPT_FILES and len(records) > MAX_PROMPT_FILES:
            QMessageBox.information(
                self,
                "Too many PDFs selected",
                f"Custom prompt extraction supports up to {MAX_PROMPT_FILES} PDFs at a time.",
            )
            return
        self._persist_ollama_settings()
        if not self.config.ollama_model.strip():
            QMessageBox.information(self, "No Ollama model", "Enter a local Ollama model name first.")
            return
        if self.ollama_thread is not None:
            return

        self._set_extraction_results([])
        self.extraction_progress_label.setText(
            f"Running local Ollama extraction for {len(records)} selected PDF(s)..."
        )
        self.extraction_elapsed_label.setText("0:00")
        self.status.setText(f"Ollama extraction running: 0/{len(records)}")
        self.run_extraction_button.setEnabled(False)
        self.stop_ollama_button.setEnabled(True)
        self.ollama_stop_event = Event()
        self.ollama_start_time = time.monotonic()
        self.ollama_last_progress_text = "Starting Ollama extraction..."
        self.ollama_timer.start()
        self.ollama_thread = QThread(self)
        self.ollama_worker = OllamaExtractionWorker(
            records=records,
            model=self.config.ollama_model,
            base_url=self.config.ollama_base_url,
            timeout_seconds=self.config.ollama_timeout_seconds,
            options=self._ollama_options(),
            extraction_backend=self.config.extraction_backend,
            prompt_template=self.config.extraction_prompt,
            stop_event=self.ollama_stop_event,
        )
        self.ollama_worker.moveToThread(self.ollama_thread)
        self.ollama_thread.started.connect(self.ollama_worker.run)
        self.ollama_worker.progress.connect(self._ollama_extraction_progress)
        self.ollama_worker.finished.connect(self._ollama_extraction_finished)
        self.ollama_worker.failed.connect(self._ollama_extraction_failed)
        self.ollama_worker.finished.connect(self.ollama_thread.quit)
        self.ollama_worker.failed.connect(self.ollama_thread.quit)
        self.ollama_worker.finished.connect(self.ollama_worker.deleteLater)
        self.ollama_worker.failed.connect(self.ollama_worker.deleteLater)
        self.ollama_thread.finished.connect(self.ollama_thread.deleteLater)
        self.ollama_thread.finished.connect(self._ollama_thread_deleted)
        self.ollama_thread.start()

    @Slot(int, int, str)
    def _ollama_extraction_progress(self, current: int, total: int, file_name: str) -> None:
        self.ollama_last_progress_text = f"Ollama extraction running: {current}/{total} - {file_name}"
        message = self.ollama_last_progress_text
        self.status.setText(message)
        self.extraction_progress_label.setText(message + ". The app is still working.")

    @Slot(object)
    def _ollama_extraction_finished(self, results: object) -> None:
        self.ollama_timer.stop()
        self._set_extraction_results(results if isinstance(results, list) else [])
        elapsed = self._format_elapsed(time.monotonic() - (self.ollama_start_time or time.monotonic()))
        finished_text = "Ollama extraction stopped" if self.ollama_stop_event and self.ollama_stop_event.is_set() else "Ollama extraction complete"
        self.extraction_progress_label.setText(f"{finished_text} in {elapsed}")
        self.ollama_parameters_label.setText("Parameters: " + self._ollama_settings_summary())
        self.run_extraction_button.setEnabled(True)
        self.stop_ollama_button.setEnabled(False)
        self.status.setText(f"{finished_text} in {elapsed}")

    @Slot(str)
    def _ollama_extraction_failed(self, message: str) -> None:
        self.ollama_timer.stop()
        elapsed = self._format_elapsed(time.monotonic() - (self.ollama_start_time or time.monotonic()))
        self._set_extraction_results(
            [{"file_name": "", "full_path": "", "status": "error", "result": "Ollama extraction failed: " + message}]
        )
        self.extraction_progress_label.setText(f"Ollama extraction failed after {elapsed}")
        self.run_extraction_button.setEnabled(True)
        self.stop_ollama_button.setEnabled(False)
        self.status.setText(f"Ollama extraction failed after {elapsed}")

    @Slot()
    def stop_ollama_extraction(self) -> None:
        if self.ollama_stop_event is None:
            return
        self.ollama_stop_event.set()
        self.stop_ollama_button.setEnabled(False)
        self.status.setText("Stopping Ollama extraction...")
        self.extraction_progress_label.setText("Stopping Ollama extraction...")

    def _ollama_timer_tick(self) -> None:
        if self.ollama_start_time is None:
            return
        self._update_ollama_timer_label()

    def _update_ollama_timer_label(self) -> None:
        elapsed = self._format_elapsed(time.monotonic() - (self.ollama_start_time or time.monotonic()))
        self.extraction_elapsed_label.setText(elapsed)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        minutes = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{minutes}:{secs:02d}"

    @Slot()
    def _ollama_thread_deleted(self) -> None:
        self.ollama_thread = None
        self.ollama_worker = None

    def _visible_records(self) -> list[PdfRecord]:
        records: list[PdfRecord] = []
        for row in range(self.proxy.rowCount()):
            proxy_index = self.proxy.index(row, 0)
            source_index = self.proxy.mapToSource(proxy_index)
            record = self.model.record_at(source_index.row())
            if record is not None:
                records.append(record)
        return records

    def _set_extraction_results(self, results: list[dict[str, str]]) -> None:
        self.extraction_result_table.setRowCount(0)
        latest_pdf_row = -1
        latest_pdf_name = ""
        latest_pdf_path = ""
        for row_data in results:
            row = self.extraction_result_table.rowCount()
            self.extraction_result_table.insertRow(row)
            values = [
                row_data.get("file_name", ""),
                row_data.get("full_path", ""),
                row_data.get("status", ""),
                row_data.get("result", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setForeground(QColor("#0f172a"))
                item.setBackground(QColor("#ffffff"))
                self.extraction_result_table.setItem(row, column, item)
            path = row_data.get("full_path", "")
            if path:
                latest_pdf_row = row
                latest_pdf_name = row_data.get("file_name", "") or Path(path).name
                latest_pdf_path = path
            open_button = self._button("Open", QStyle.SP_FileIcon)
            open_button.setToolTip("Open this PDF")
            open_button.setEnabled(bool(path))
            open_button.clicked.connect(lambda checked=False, pdf_path=path: self._open_pdf_path(pdf_path))
            self.extraction_result_table.setCellWidget(row, 4, open_button)
        self.extraction_result_table.resizeColumnsToContents()
        self.extraction_result_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._set_latest_extraction_pdf(latest_pdf_name, latest_pdf_path)
        if latest_pdf_row >= 0:
            self.extraction_result_table.selectRow(latest_pdf_row)
            self.extraction_result_table.scrollToItem(self.extraction_result_table.item(latest_pdf_row, 0))

    def _set_latest_extraction_pdf(self, file_name: str, path: str) -> None:
        self.latest_extraction_pdf_path = path
        self.open_latest_extraction_pdf_button.setEnabled(bool(path))
        if path:
            self.latest_extraction_pdf_label.setText(file_name or Path(path).name)
        else:
            self.latest_extraction_pdf_label.setText("No extracted PDF available.")

    def _folder_filter_changed(self, value: str) -> None:
        self.proxy.set_folder("" if value == "All folders" else value)
        self._update_scan_summary()

    def _page_filter_changed(self) -> None:
        minimum = self.min_pages.value() or None
        maximum = self.max_pages.value() or None
        self.proxy.set_page_range(minimum, maximum)
        self._update_scan_summary()

    def _size_filter_changed(self) -> None:
        minimum = self.min_size.value() or None
        maximum = self.max_size.value() or None
        self.proxy.set_size_range(minimum, maximum)
        self._update_scan_summary()

    def _encrypted_filter_changed(self, index: int) -> None:
        self.proxy.set_encrypted_filter(None if index == 0 else index == 1)
        self._update_scan_summary()

    def _text_filter_changed(self, index: int) -> None:
        self.proxy.set_text_extractable_filter(None if index == 0 else index == 1)
        self._update_scan_summary()

    def _extraction_backend_changed(self) -> None:
        is_docling = self._selected_extraction_backend() == "docling"
        self.docling_warning_label.setVisible(is_docling)
        self._update_docling_availability_label()
        if is_docling:
            self.status.setText("Docling extraction selected. PDF extraction can take more time.")

    def _update_docling_availability_label(self) -> None:
        is_docling = self._selected_extraction_backend() == "docling"
        available = is_docling_available()
        self.docling_availability_label.setVisible(is_docling or not available)
        if available:
            self.docling_availability_label.setText("Docling is installed and available.")
            self.docling_availability_label.setStyleSheet("color: #166534; font-size: 11px;")
        else:
            self.docling_availability_label.setText(
                'Docling is not installed. Install it with: python -m pip install -e ".[docling,test]"'
            )
            self.docling_availability_label.setStyleSheet("color: #991b1b; font-size: 11px;")

    def _update_folder_filter_options(self) -> None:
        current = self.folder_filter.currentText() if hasattr(self, "folder_filter") else "All folders"
        folders = sorted({record.parent_folder for record in self.model.records})
        self.folder_filter.blockSignals(True)
        self.folder_filter.clear()
        self.folder_filter.addItem("All folders")
        self.folder_filter.addItems(folders)
        if current in {"All folders", *folders}:
            self.folder_filter.setCurrentText(current)
        self.folder_filter.blockSignals(False)

    def _update_folder_label(self) -> None:
        if self.selected_folders:
            selected = "; ".join(self.selected_folders)
        else:
            selected = "none"
        self.folder_label.setText(f"Selected folders: {selected} | Current scan scope: {self._scan_scope_label()}")
        self._update_selected_folder_options()
        self._update_scan_summary()

    def _update_selected_folder_options(self) -> None:
        if not hasattr(self, "selected_folder_input"):
            return
        current = self.selected_folder_input.currentData()
        self.selected_folder_input.blockSignals(True)
        self.selected_folder_input.clear()
        for folder in self.selected_folders:
            self.selected_folder_input.addItem(folder, folder)
        if current in self.selected_folders:
            self.selected_folder_input.setCurrentIndex(self.selected_folders.index(current))
        self.selected_folder_input.blockSignals(False)
        has_folders = bool(self.selected_folders)
        self.selected_folder_input.setEnabled(has_folders)
        self.remove_folder_button.setEnabled(has_folders)

    def _update_scan_summary(self) -> None:
        found_count = self.model.rowCount()
        visible_count = self.proxy.rowCount()
        locations = self._scan_scope_label()
        self.scan_summary_label.setText(
            f"Found PDF files: {found_count} | Visible after filters: {visible_count} | Scan locations: {locations}"
        )
        self.distribution_chart.set_records(self._visible_records())

    def _scan_scope_label(self) -> str:
        if self.current_scan_roots == [WHOLE_MACHINE_ROOT]:
            return "entire machine (/)"
        if self.current_scan_roots:
            return "; ".join(self.current_scan_roots)
        return "none"

    def _persist_folders(self) -> None:
        self.config.last_selected_folders = self.selected_folders.copy()
        self.config.visible_columns = self.model.columns.copy()
        self.config.save()

    def _persist_ollama_settings(self) -> None:
        self.config.ollama_base_url = self.ollama_base_url_input.text().strip() or "http://localhost:11434"
        self.config.ollama_model = self.ollama_model_input.text().strip()
        self.config.ollama_temperature = self.ollama_temperature_input.value()
        self.config.ollama_top_p = self.ollama_top_p_input.value()
        self.config.ollama_top_k = self.ollama_top_k_input.value()
        self.config.ollama_num_predict = self.ollama_num_predict_input.value()
        self.config.ollama_num_ctx = self.ollama_num_ctx_input.value()
        self.config.ollama_timeout_seconds = self.ollama_timeout_input.value()
        self.config.extraction_backend = self._selected_extraction_backend()
        self.config.extraction_prompt = self.prompt_input.toPlainText()
        self.config.save()

    def _selected_extraction_backend(self) -> str:
        if self.docling_backend_option.isChecked():
            return "docling"
        return "pypdf"

    def _ollama_options(self) -> dict[str, float | int]:
        options: dict[str, float | int] = {
            "temperature": self.config.ollama_temperature,
            "top_p": self.config.ollama_top_p,
        }
        if self.config.ollama_top_k > 0:
            options["top_k"] = self.config.ollama_top_k
        if self.config.ollama_num_predict > 0:
            options["num_predict"] = self.config.ollama_num_predict
        if self.config.ollama_num_ctx > 0:
            options["num_ctx"] = self.config.ollama_num_ctx
        return options

    def _ollama_settings_summary(self) -> str:
        top_k = str(self.config.ollama_top_k) if self.config.ollama_top_k > 0 else "Auto"
        max_tokens = str(self.config.ollama_num_predict) if self.config.ollama_num_predict > 0 else "Auto"
        context = str(self.config.ollama_num_ctx) if self.config.ollama_num_ctx > 0 else "Auto"
        return (
            f"model {self.config.ollama_model or 'none'}, "
            f"PDF text {self._extraction_backend_label(self.config.extraction_backend)}, "
            f"temperature {self.config.ollama_temperature:.2f}, "
            f"top-p {self.config.ollama_top_p:.2f}, "
            f"top-k {top_k}, max tokens {max_tokens}, context {context}, "
            f"timeout {self.config.ollama_timeout_seconds}s"
        )

    @staticmethod
    def _extraction_backend_label(value: str) -> str:
        if value == "docling":
            return "Docling"
        return "pypdf"

    def _reset_prompt_to_default(self) -> None:
        self.prompt_input.setPlainText(DEFAULT_EXTRACTION_PROMPT)
        self.status.setText("Extraction prompt reset to default.")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.scan_thread is not None:
            self.stop_event.set()
            self.scan_thread.quit()
            self.scan_thread.wait(3000)
        if self.ollama_thread is not None:
            self.ollama_thread.quit()
            self.ollama_thread.wait(3000)
        self._persist_folders()
        self._persist_ollama_settings()
        QApplication.instance().quit()
        event.accept()
