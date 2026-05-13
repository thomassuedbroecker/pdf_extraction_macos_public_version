"""Main PySide6 window for the PDF Manager app."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
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
    QPlainTextEdit,
    QSpinBox,
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
from pdf_manager.core.prompts import render_prompt
from pdf_manager.core.scanner import PdfScanner
from pdf_manager.integrations.ollama_client import OllamaClient
from pdf_manager.models.pdf_record import PdfRecord
from pdf_manager.ui.distribution_chart import DistributionChartWidget
from pdf_manager.ui.table_model import DEFAULT_COLUMNS, PdfFilterProxyModel, PdfTableModel

LOGGER = logging.getLogger(__name__)
WHOLE_MACHINE_ROOT = "/"
MAX_PROMPT_FILES = 10


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

    def __init__(self, records: list[PdfRecord], model: str, base_url: str, prompt_template: str) -> None:
        super().__init__()
        self.records = records
        self.model = model
        self.base_url = base_url
        self.prompt_template = prompt_template

    @Slot()
    def run(self) -> None:
        try:
            client = OllamaClient(base_url=self.base_url)
            result_rows: list[dict[str, str]] = []
            total = len(self.records)
            for current, record in enumerate(self.records, start=1):
                self.progress.emit(current, total, record.file_name)
                try:
                    text = extract_pdf_text(record.full_path)
                    if not text.strip():
                        result_rows.append(_extraction_result_row(record, "error", "No extractable text found in PDF"))
                        continue
                    prompt = render_prompt(self.prompt_template, record, text)
                    result = client.generate(prompt=prompt, model=self.model)
                    result_rows.append(_extraction_result_row(record, "complete", result or "Ollama returned an empty response."))
                except Exception as exc:
                    LOGGER.exception("Ollama extraction failed for %s", record.full_path)
                    result_rows.append(_extraction_result_row(record, "error", str(exc)))
            self.finished.emit(result_rows)
        except Exception as exc:
            LOGGER.exception("Ollama extraction failed")
            self.failed.emit(str(exc))


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

        self.model = PdfTableModel(config.visible_columns or DEFAULT_COLUMNS.copy())
        self.proxy = PdfFilterProxyModel()
        self.proxy.setSourceModel(self.model)

        self.setWindowTitle("PDF Manager")
        self.resize(1400, 760)
        self._build_ui()
        self._update_folder_label()
        self._update_folder_filter_options()

    def _build_ui(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)

        choose_button = QPushButton("Add Folder")
        choose_button.clicked.connect(self.choose_folders)
        toolbar.addWidget(choose_button)

        self.start_button = QPushButton("Start Scan")
        self.start_button.clicked.connect(self.start_scan)
        toolbar.addWidget(self.start_button)

        self.scan_all_button = QPushButton("Scan Entire Machine")
        self.scan_all_button.clicked.connect(self.start_entire_machine_scan)
        toolbar.addWidget(self.scan_all_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_scan)
        self.stop_button.setEnabled(False)
        toolbar.addWidget(self.stop_button)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_scan)
        toolbar.addWidget(refresh_button)

        export_button = QPushButton("Export XLSX")
        export_button.clicked.connect(self.export_current_view)
        toolbar.addWidget(export_button)

        open_button = QPushButton("Open PDF")
        open_button.clicked.connect(self.open_selected_pdf)
        toolbar.addWidget(open_button)

        reveal_button = QPushButton("Reveal in Finder")
        reveal_button.clicked.connect(self.reveal_selected_pdf)
        toolbar.addWidget(reveal_button)

        central = QWidget()
        layout = QVBoxLayout(central)

        self.folder_label = QLabel()
        layout.addWidget(self.folder_label)

        self.scan_summary_label = QLabel()
        self.scan_summary_label.setWordWrap(True)
        layout.addWidget(self.scan_summary_label)

        self.distribution_chart = DistributionChartWidget()
        layout.addWidget(self.distribution_chart)

        filter_layout = QFormLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search file name, path, metadata, preview, or errors")
        self.search_input.textChanged.connect(self.proxy.set_search_text)
        self.search_input.textChanged.connect(lambda _: self._update_scan_summary())
        filter_layout.addRow("Search", self.search_input)

        self.folder_filter = QComboBox()
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
        filter_layout.addRow("Size", size_range)

        self.encrypted_filter = QComboBox()
        self.encrypted_filter.addItems(["Any", "Encrypted", "Not encrypted"])
        self.encrypted_filter.currentIndexChanged.connect(self._encrypted_filter_changed)
        filter_layout.addRow("Encryption", self.encrypted_filter)

        self.text_filter = QComboBox()
        self.text_filter.addItems(["Any", "Text extractable", "Not text extractable"])
        self.text_filter.currentIndexChanged.connect(self._text_filter_changed)
        filter_layout.addRow("Text", self.text_filter)

        layout.addLayout(filter_layout)

        ollama_layout = QFormLayout()
        self.ollama_base_url_input = QLineEdit(self.config.ollama_base_url)
        ollama_layout.addRow("Ollama URL", self.ollama_base_url_input)

        model_row = QHBoxLayout()
        self.ollama_model_input = QLineEdit(self.config.ollama_model)
        self.ollama_model_input.setPlaceholderText("example: llama3.1:8b")
        self.refresh_models_button = QPushButton("Refresh Models")
        self.refresh_models_button.clicked.connect(self.refresh_ollama_models)
        model_row.addWidget(self.ollama_model_input)
        model_row.addWidget(self.refresh_models_button)
        ollama_layout.addRow("Ollama Model", model_row)

        self.prompt_input = QPlainTextEdit()
        self.prompt_input.setPlainText(self.config.extraction_prompt)
        self.prompt_input.setPlaceholderText(
            "Use placeholders such as {file_name}, {full_path}, {page_count}, {text}, and {documents}"
        )
        self.prompt_input.setMaximumHeight(130)
        ollama_layout.addRow("Extraction Prompt", self.prompt_input)

        run_prompt_row = QHBoxLayout()
        self.run_extraction_button = QPushButton("Run Prompt on Selected PDFs")
        self.run_extraction_button.clicked.connect(self.run_ollama_extraction)
        self.save_prompt_button = QPushButton("Save Prompt Settings")
        self.save_prompt_button.clicked.connect(self._persist_ollama_settings)
        run_prompt_row.addWidget(self.run_extraction_button)
        run_prompt_row.addWidget(self.save_prompt_button)
        ollama_layout.addRow("Local Extraction", run_prompt_row)

        self.extraction_progress_label = QLabel("No local extraction running.")
        ollama_layout.addRow("Extraction Progress", self.extraction_progress_label)

        self.extraction_result_table = QTableWidget(0, 4)
        self.extraction_result_table.setHorizontalHeaderLabels(["File", "Path", "Status", "Result / Error"])
        self.extraction_result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.extraction_result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.extraction_result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.extraction_result_table.horizontalHeader().setStretchLastSection(True)
        self.extraction_result_table.setMaximumHeight(180)
        ollama_layout.addRow("Extraction Result", self.extraction_result_table)

        layout.addLayout(ollama_layout)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.doubleClicked.connect(lambda _: self.open_selected_pdf())
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, stretch=1)

        self.status = QLabel("Ready")
        layout.addWidget(self.status)

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
        subprocess.run(["open", record.full_path], check=False)

    @Slot()
    def reveal_selected_pdf(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        subprocess.run(["open", "-R", record.full_path], check=False)

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
            QMessageBox.information(self, "No PDF selected", "Select one to ten PDF rows first.")
            return
        if len(records) > MAX_PROMPT_FILES:
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
        self.status.setText(f"Ollama extraction running: 0/{len(records)}")
        self.run_extraction_button.setEnabled(False)
        self.ollama_thread = QThread(self)
        self.ollama_worker = OllamaExtractionWorker(
            records=records,
            model=self.config.ollama_model,
            base_url=self.config.ollama_base_url,
            prompt_template=self.config.extraction_prompt,
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
        message = f"Ollama extraction running: {current}/{total} - {file_name}"
        self.status.setText(message)
        self.extraction_progress_label.setText(message + " | The app is still working.")

    @Slot(object)
    def _ollama_extraction_finished(self, results: object) -> None:
        self._set_extraction_results(results if isinstance(results, list) else [])
        self.extraction_progress_label.setText("Ollama extraction complete")
        self.run_extraction_button.setEnabled(True)
        self.status.setText("Ollama extraction complete")

    @Slot(str)
    def _ollama_extraction_failed(self, message: str) -> None:
        self._set_extraction_results(
            [{"file_name": "", "full_path": "", "status": "error", "result": "Ollama extraction failed: " + message}]
        )
        self.extraction_progress_label.setText("Ollama extraction failed")
        self.run_extraction_button.setEnabled(True)
        self.status.setText("Ollama extraction failed")

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
                self.extraction_result_table.setItem(row, column, QTableWidgetItem(value))
        self.extraction_result_table.resizeColumnsToContents()

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
        self._update_scan_summary()

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
        self.config.extraction_prompt = self.prompt_input.toPlainText()
        self.config.save()

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
