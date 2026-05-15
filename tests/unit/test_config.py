from __future__ import annotations

from pathlib import Path

import pytest

from pdf_manager.core.config import AppConfig


pytestmark = pytest.mark.unit


def test_config_saves_and_loads_user_settings(monkeypatch: pytest.MonkeyPatch, temporary_config_path: Path) -> None:
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))
    config = AppConfig(
        last_selected_folders=["/tmp/pdfs"],
        last_export_location="/tmp",
        visible_columns=["file_name", "page_count"],
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.1:8b",
        ollama_temperature=0.4,
        ollama_top_p=0.8,
        ollama_top_k=30,
        ollama_num_predict=2048,
        ollama_num_ctx=8192,
        ollama_timeout_seconds=180,
        extraction_prompt="Extract {text}",
    )

    config.save()
    loaded = AppConfig.load()

    assert loaded.last_selected_folders == ["/tmp/pdfs"]
    assert loaded.last_export_location == "/tmp"
    assert loaded.visible_columns == ["file_name", "page_count"]
    assert loaded.ollama_base_url == "http://localhost:11434"
    assert loaded.ollama_model == "llama3.1:8b"
    assert loaded.ollama_temperature == 0.4
    assert loaded.ollama_top_p == 0.8
    assert loaded.ollama_top_k == 30
    assert loaded.ollama_num_predict == 2048
    assert loaded.ollama_num_ctx == 8192
    assert loaded.ollama_timeout_seconds == 180
    assert loaded.extraction_prompt == "Extract {text}"


def test_config_uses_platformdirs_application_path() -> None:
    path = AppConfig.config_path()

    assert path.name == "config.json"
    assert "PDF Manager" in str(path)


def test_config_handles_missing_config_file(monkeypatch: pytest.MonkeyPatch, temporary_config_path: Path) -> None:
    monkeypatch.setattr(AppConfig, "config_path", staticmethod(lambda: temporary_config_path))

    config = AppConfig.load()

    assert config.last_selected_folders == []
    assert config.last_export_location is None
    assert "file_name" in config.visible_columns
    assert config.ollama_base_url == "http://localhost:11434"
    assert config.ollama_model == ""
    assert config.ollama_temperature == 0.2
    assert config.ollama_top_p == 0.9
    assert config.ollama_top_k == 40
    assert config.ollama_num_predict == 1024
    assert config.ollama_num_ctx == 4096
    assert config.ollama_timeout_seconds == 120
    assert "{text}" in config.extraction_prompt
