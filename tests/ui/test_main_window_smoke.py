from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox

from pdf_manager.core.config import AppConfig
from pdf_manager.models.pdf_record import PdfRecord
from pdf_manager.ui.main_window import MAX_PROMPT_FILES, MainWindow, WHOLE_MACHINE_ROOT


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
