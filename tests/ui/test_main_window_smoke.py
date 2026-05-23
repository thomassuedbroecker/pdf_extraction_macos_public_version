from __future__ import annotations

from threading import Event

import pytest
from openpyxl import load_workbook

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from pdf_manager.core.config import AppConfig
from pdf_manager.models.pdf_record import PdfRecord
from pdf_manager.ui.main_window import WHOLE_MACHINE_ROOT, MainWindow, OllamaExtractionWorker

pytestmark = pytest.mark.ui


@pytest.fixture
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_can_be_created(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))

    window = MainWindow(config=AppConfig())

    assert window.windowTitle() == "PDF Manager"
    assert window.app_title_label.text() == "PDF Manager - Python desktop app"
    assert window.model.rowCount() == 0
    assert "Found PDF files: 0" in window.scan_summary_label.text()
    assert "{text}" in window.prompt_input.toPlainText()
    assert "Keep one PDF text variable" in window.prompt_parameters_label.text()
    assert window.prompt_variable_status_label.text() == "PDF text variable found."
    window.close()


def test_main_window_warns_when_prompt_text_variable_is_missing(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))

    window = MainWindow(config=AppConfig())

    window.prompt_input.setPlainText("Summarize {file_name}")

    assert "PDF text variable missing" in window.prompt_variable_status_label.text()
    assert "{text} or {documents}" in window.prompt_variable_status_label.text()
    window.close()


def test_main_window_can_start_entire_machine_scan_without_selected_folder(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    captured_roots: list[str] = []

    window = MainWindow(config=AppConfig())
    monkeypatch.setattr(window, "_start_scan", lambda roots: captured_roots.extend(roots))

    window.start_entire_machine_scan()

    assert captured_roots == [WHOLE_MACHINE_ROOT]
    window.close()


def test_main_window_scan_summary_shows_found_files_and_locations(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path, sample_pdf_records: list[PdfRecord]
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))

    window = MainWindow(config=AppConfig(last_selected_folders=["/tmp/a", "/tmp/b"]))
    window.current_scan_roots = ["/tmp/a", "/tmp/b"]

    for record in sample_pdf_records:
        window._record_found(record)

    summary = window.scan_summary_label.text()

    assert "Found PDF files: 2" in summary
    assert "Visible after filters: 2" in summary
    assert "Scan locations: /tmp/a; /tmp/b" in summary
    assert sum(item.count for item in window.distribution_chart.page_bins) == 2
    assert sum(item.count for item in window.distribution_chart.size_bins) == 2
    window.close()


def test_main_window_removes_selected_folder(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))

    window = MainWindow(config=AppConfig(last_selected_folders=["/tmp/a", "/tmp/b"]))
    window.current_scan_roots = ["/tmp/a", "/tmp/b"]
    window.selected_folder_input.setCurrentIndex(0)

    window.remove_selected_folder()

    loaded = AppConfig.load()
    assert window.selected_folders == ["/tmp/b"]
    assert window.current_scan_roots == ["/tmp/b"]
    assert loaded.last_selected_folders == ["/tmp/b"]
    assert window.selected_folder_input.count() == 1
    assert window.selected_folder_input.itemText(0) == "/tmp/b"
    window.close()


def test_main_window_persists_custom_ollama_prompt_settings(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))
    window = MainWindow(config=AppConfig())
    window.ollama_base_url_input.setText("http://localhost:11434")
    window.ollama_model_input.setText("llama3.1:8b")
    window.ollama_temperature_input.setValue(0.35)
    window.ollama_top_p_input.setValue(0.75)
    window.ollama_top_k_input.setValue(25)
    window.ollama_num_predict_input.setValue(2048)
    window.ollama_num_ctx_input.setValue(8192)
    window.ollama_timeout_input.setValue(180)
    window.docling_backend_option.setChecked(True)
    window.prompt_input.setPlainText("Extract invoice fields from {file_name}:\n{text}")

    window._persist_ollama_settings()
    loaded = AppConfig.load()

    assert loaded.ollama_base_url == "http://localhost:11434"
    assert loaded.ollama_model == "llama3.1:8b"
    assert loaded.ollama_temperature == 0.35
    assert loaded.ollama_top_p == 0.75
    assert loaded.ollama_top_k == 25
    assert loaded.ollama_num_predict == 2048
    assert loaded.ollama_num_ctx == 8192
    assert loaded.ollama_timeout_seconds == 180
    assert loaded.extraction_backend == "docling"
    assert "Extract invoice fields" in loaded.extraction_prompt
    window.close()


def test_main_window_resets_prompt_to_default(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))
    window = MainWindow(config=AppConfig())

    window.prompt_input.setPlainText("Custom prompt text")
    window._reset_prompt_to_default()

    assert "You are extracting useful information from a local PDF." in window.prompt_input.toPlainText()
    assert "Extraction prompt reset to default." in window.status.text()
    window.close()


def test_main_window_allows_more_than_ten_prompt_extraction_files(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    temporary_config_path,
    sample_pdf_records: list[PdfRecord],
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))
    monkeypatch.setattr("pdf_manager.ui.main_window.QThread.start", lambda self: None)
    messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))

    window = MainWindow(config=AppConfig(ollama_model="llama3.1:8b"))
    selected_records = [sample_pdf_records[0] for _ in range(12)]
    monkeypatch.setattr(window, "_selected_records", lambda: selected_records)

    window.run_ollama_extraction()

    assert messages == []
    assert window.ollama_thread is not None
    assert window.ollama_worker is not None
    assert window.ollama_worker.options["temperature"] == 0.2
    assert window.ollama_worker.timeout_seconds == 120
    assert window.ollama_worker.extraction_backend == "pypdf"
    window.close()


def test_main_window_shows_docling_extraction_warning(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))
    monkeypatch.setattr("pdf_manager.ui.main_window.is_docling_available", lambda: False)

    window = MainWindow(config=AppConfig(extraction_backend="docling"))

    assert window.docling_backend_option.isChecked()
    assert window.pypdf_backend_option.text() == "Default pypdf"
    assert window.docling_backend_option.text() == "Docling slower"
    assert not window.docling_warning_label.isHidden()
    assert "more time" in window.docling_warning_label.text()
    assert "Docling is not installed" in window.docling_availability_label.text()
    window.close()


def test_main_window_shows_ollama_extraction_progress(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))

    window = MainWindow(config=AppConfig())

    window._ollama_extraction_progress(2, 5, "report.pdf")

    assert "Ollama extraction running: 2/5 - report.pdf" in window.status.text()
    assert "The app is still working" in window.extraction_progress_label.text()
    window.close()


def test_main_window_shows_ollama_extraction_results_in_table(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))

    window = MainWindow(config=AppConfig())

    window._ollama_extraction_finished(
        [
            {
                "file_name": "report.pdf",
                "full_path": "/tmp/report.pdf",
                "status": "complete",
                "result": "Summary for report",
            }
        ]
    )

    assert window.extraction_result_table.rowCount() == 1
    assert window.extraction_result_table.item(0, 0).text() == "report.pdf"
    assert window.extraction_result_table.item(0, 1).text() == "/tmp/report.pdf"
    assert window.extraction_result_table.item(0, 2).text() == "complete"
    assert window.extraction_result_table.item(0, 3).text() == "Summary for report"
    assert window.extraction_result_table.cellWidget(0, 4) is not None
    assert window.latest_extraction_pdf_label.text() == "report.pdf"
    assert window.open_latest_extraction_pdf_button.isEnabled()
    assert window.export_results_button.isEnabled()
    assert "temperature" in window.ollama_parameters_label.text()
    window.close()


def test_main_window_opens_pdf_from_extraction_results(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    opened: list[list[str]] = []
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda args, **kwargs: opened.append(args))
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))

    window = MainWindow(config=AppConfig())
    window._set_extraction_results(
        [
            {
                "file_name": "report.pdf",
                "full_path": "/tmp/report.pdf",
                "status": "complete",
                "result": "Summary for report",
            }
        ]
    )
    window.extraction_result_table.selectRow(0)

    window.open_selected_extraction_pdf()

    assert opened == [["open", "/tmp/report.pdf"]]
    window.close()


def test_main_window_opens_latest_extracted_pdf(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    opened: list[list[str]] = []
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda args, **kwargs: opened.append(args))
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))

    window = MainWindow(config=AppConfig())
    window._set_extraction_results(
        [
            {
                "file_name": "first.pdf",
                "full_path": "/tmp/first.pdf",
                "status": "complete",
                "result": "First",
            },
            {
                "file_name": "latest.pdf",
                "full_path": "/tmp/latest.pdf",
                "status": "complete",
                "result": "Latest",
            },
        ]
    )

    window.open_latest_extraction_pdf()

    assert window.latest_extraction_pdf_label.text() == "latest.pdf"
    assert opened == [["open", "/tmp/latest.pdf"]]
    window.close()


def test_main_window_clears_model_extraction_results(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))

    window = MainWindow(config=AppConfig())
    window._ollama_extraction_finished(
        [
            {
                "file_name": "report.pdf",
                "full_path": "/tmp/report.pdf",
                "status": "complete",
                "result": "Summary for report",
            }
        ]
    )

    window.clear_extraction_results()

    assert window.extraction_result_table.rowCount() == 0
    assert window.latest_extraction_pdf_path == ""
    assert window.latest_extraction_pdf_label.text() == "No extracted PDF available."
    assert not window.open_latest_extraction_pdf_button.isEnabled()
    assert not window.export_results_button.isEnabled()
    assert window.extraction_progress_label.text() == "No local extraction running."
    assert window.extraction_elapsed_label.text() == "0:00"
    assert window.ollama_parameters_label.text() == "Parameters: not used yet"
    assert window.status.text() == "Model extraction results cleared."
    window.close()


def test_main_window_exports_model_extraction_results(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, temporary_config_path, tmp_path
) -> None:
    monkeypatch.setattr("pdf_manager.ui.main_window.subprocess.run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))
    output = tmp_path / "llm-results.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(output), "Excel Workbook (*.xlsx)"))

    window = MainWindow(config=AppConfig())
    window._set_extraction_results(
        [
            {
                "file_name": "report.pdf",
                "full_path": "/tmp/report.pdf",
                "status": "complete",
                "result": "Summary for report",
            }
        ]
    )

    window.export_extraction_results()

    workbook = load_workbook(output)
    sheet = workbook["LLM Results"]
    assert sheet["A2"].value == "report.pdf"
    assert sheet["D2"].value == "Summary for report"
    assert "Exported 1 model result rows" in window.status.text()
    window.close()


def test_ollama_worker_always_sends_extracted_text_to_model(
    monkeypatch: pytest.MonkeyPatch, sample_pdf_records: list[PdfRecord]
) -> None:
    prompts: list[str] = []
    finished_results: list[object] = []

    class FakeOllamaClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def generate(self, prompt: str, model: str, options: dict) -> str:
            prompts.append(prompt)
            return "model result"

    monkeypatch.setattr("pdf_manager.ui.main_window.extract_pdf_text", lambda path: "Extracted body text")
    monkeypatch.setattr("pdf_manager.ui.main_window.OllamaClient", FakeOllamaClient)

    worker = OllamaExtractionWorker(
        records=[sample_pdf_records[0]],
        model="llama3.1:8b",
        base_url="http://localhost:11434",
        timeout_seconds=120,
        options={},
        extraction_backend="pypdf",
        prompt_template="Summarize {file_name}",
        stop_event=Event(),
    )
    worker.finished.connect(lambda results: finished_results.append(results))

    worker.run()

    assert prompts == ["Summarize alpha.pdf\n\nPDF text:\nExtracted body text"]
    assert finished_results
