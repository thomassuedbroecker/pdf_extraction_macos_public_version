"""Typed data model for PDF scan results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PdfRecord:
    """Represents one discovered PDF and its extracted metadata."""

    file_name: str
    full_path: str
    parent_folder: str
    file_size_bytes: int
    created_date: datetime | None
    modified_date: datetime | None
    page_count: int | None = None
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    producer: str | None = None
    encrypted: bool | None = None
    text_extractable: bool | None = None
    text_preview: str | None = None
    error: str | None = None

    @property
    def file_size_mb(self) -> float:
        """Return the file size in MiB."""
        return self.file_size_bytes / (1024 * 1024)

    @classmethod
    def from_path(cls, path: Path, error: str | None = None) -> "PdfRecord":
        """Create a record with filesystem metadata only."""
        stat = path.stat()
        return cls(
            file_name=path.name,
            full_path=str(path),
            parent_folder=str(path.parent),
            file_size_bytes=stat.st_size,
            created_date=datetime.fromtimestamp(stat.st_ctime),
            modified_date=datetime.fromtimestamp(stat.st_mtime),
            error=error,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/export friendly dictionary."""
        data = asdict(self)
        data["file_size_mb"] = round(self.file_size_mb, 3)
        data["created_date"] = self.created_date.isoformat(sep=" ", timespec="seconds") if self.created_date else ""
        data["modified_date"] = (
            self.modified_date.isoformat(sep=" ", timespec="seconds") if self.modified_date else ""
        )
        return data
