"""Recursive PDF scanner."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from threading import Event

from pdf_manager.core.pdf_metadata import extract_pdf_metadata
from pdf_manager.models.pdf_record import PdfRecord

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[int, int, Path], None]
RecordCallback = Callable[[PdfRecord], None]
DiscoveryCallback = Callable[[Path], None]


class PdfScanner:
    """Find PDF files recursively and extract metadata for each file."""

    def __init__(self, include_text_preview: bool = True) -> None:
        self.include_text_preview = include_text_preview

    def discover(
        self,
        folders: Iterable[str | Path],
        stop_event: Event | None = None,
        discovery_callback: DiscoveryCallback | None = None,
    ) -> list[Path]:
        """Return sorted PDF paths under the provided folders."""
        paths: list[Path] = []
        seen: set[Path] = set()
        for folder in folders:
            if stop_event and stop_event.is_set():
                break
            root = Path(folder).expanduser()
            if not root.exists():
                LOGGER.warning("Scan root does not exist: %s", root)
                continue
            if root.is_file() and root.suffix.lower() == ".pdf":
                try:
                    resolved = root.resolve()
                except OSError:
                    LOGGER.exception("Could not resolve path %s", root)
                    continue
                if resolved not in seen:
                    paths.append(resolved)
                    seen.add(resolved)
                continue
            if not root.is_dir():
                continue

            def on_walk_error(error: OSError) -> None:
                LOGGER.warning("Could not access %s: %s", getattr(error, "filename", "unknown path"), error)

            for current_dir, dirnames, filenames in os.walk(root, topdown=True, onerror=on_walk_error, followlinks=False):
                if stop_event and stop_event.is_set():
                    dirnames.clear()
                    break
                current_path = Path(current_dir)
                if discovery_callback:
                    discovery_callback(current_path)
                for filename in filenames:
                    if not filename.lower().endswith(".pdf"):
                        continue
                    path = current_path / filename
                    try:
                        resolved = path.resolve()
                    except OSError:
                        LOGGER.exception("Could not resolve path %s", path)
                        continue
                    if resolved not in seen:
                        paths.append(resolved)
                        seen.add(resolved)
        return sorted(paths, key=lambda item: str(item).lower())

    def scan(
        self,
        folders: Iterable[str | Path],
        stop_event: Event | None = None,
        progress_callback: ProgressCallback | None = None,
        record_callback: RecordCallback | None = None,
        discovery_callback: DiscoveryCallback | None = None,
    ) -> list[PdfRecord]:
        """Scan folders and return PDF records.

        Callbacks are optional and are intended for UI progress updates.
        """
        pdf_paths = self.discover(folders, stop_event=stop_event, discovery_callback=discovery_callback)
        total = len(pdf_paths)
        records: list[PdfRecord] = []
        for index, path in enumerate(pdf_paths, start=1):
            if stop_event and stop_event.is_set():
                break
            record = extract_pdf_metadata(path, include_text_preview=self.include_text_preview)
            records.append(record)
            if record_callback:
                record_callback(record)
            if progress_callback:
                progress_callback(index, total, path)
        return records
