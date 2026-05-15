"""Local JSON configuration and logging setup."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_log_dir

from pdf_manager.core.prompts import DEFAULT_EXTRACTION_PROMPT

APP_NAME = "PDF Manager"
APP_AUTHOR = "Local PDF Tools"


DEFAULT_VISIBLE_COLUMNS = [
    "file_name",
    "full_path",
    "parent_folder",
    "file_size_mb",
    "created_date",
    "modified_date",
    "page_count",
    "title",
    "author",
    "subject",
    "producer",
    "encrypted",
    "text_extractable",
    "text_preview",
    "error",
]


@dataclass(slots=True)
class AppConfig:
    """Persisted user preferences for the desktop app."""

    last_selected_folders: list[str] = field(default_factory=list)
    last_export_location: str | None = None
    visible_columns: list[str] = field(default_factory=lambda: DEFAULT_VISIBLE_COLUMNS.copy())
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    ollama_temperature: float = 0.2
    ollama_top_p: float = 0.9
    ollama_top_k: int = 40
    ollama_num_predict: int = 1024
    ollama_num_ctx: int = 4096
    ollama_timeout_seconds: int = 120
    extraction_prompt: str = DEFAULT_EXTRACTION_PROMPT

    @staticmethod
    def config_path() -> Path:
        """Return the app config file path."""
        return Path(user_config_dir(APP_NAME, APP_AUTHOR)) / "config.json"

    @classmethod
    def load(cls) -> "AppConfig":
        """Load user configuration from disk, falling back to defaults."""
        path = cls.config_path()
        if not path.exists():
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                last_selected_folders=list(payload.get("last_selected_folders", [])),
                last_export_location=payload.get("last_export_location"),
                visible_columns=list(payload.get("visible_columns", DEFAULT_VISIBLE_COLUMNS)),
                ollama_base_url=str(payload.get("ollama_base_url", "http://localhost:11434")),
                ollama_model=str(payload.get("ollama_model", "")),
                ollama_temperature=float(payload.get("ollama_temperature", 0.2)),
                ollama_top_p=float(payload.get("ollama_top_p", 0.9)),
                ollama_top_k=int(payload.get("ollama_top_k", 40)),
                ollama_num_predict=int(payload.get("ollama_num_predict", 1024)),
                ollama_num_ctx=int(payload.get("ollama_num_ctx", 4096)),
                ollama_timeout_seconds=int(payload.get("ollama_timeout_seconds", 120)),
                extraction_prompt=str(payload.get("extraction_prompt", DEFAULT_EXTRACTION_PROMPT)),
            )
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logging.getLogger(__name__).warning("Failed to load config %s: %s", path, exc)
            return cls()

    def save(self) -> None:
        """Persist user configuration to disk."""
        path = self.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "last_selected_folders": self.last_selected_folders,
            "last_export_location": self.last_export_location,
            "visible_columns": self.visible_columns,
            "ollama_base_url": self.ollama_base_url,
            "ollama_model": self.ollama_model,
            "ollama_temperature": self.ollama_temperature,
            "ollama_top_p": self.ollama_top_p,
            "ollama_top_k": self.ollama_top_k,
            "ollama_num_predict": self.ollama_num_predict,
            "ollama_num_ctx": self.ollama_num_ctx,
            "ollama_timeout_seconds": self.ollama_timeout_seconds,
            "extraction_prompt": self.extraction_prompt,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def log_file_path() -> Path:
    """Return the application log file path."""
    return Path(user_log_dir(APP_NAME, APP_AUTHOR)) / "pdf_manager.log"


def configure_logging() -> None:
    """Configure file logging for application diagnostics."""
    path = log_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()],
    )
