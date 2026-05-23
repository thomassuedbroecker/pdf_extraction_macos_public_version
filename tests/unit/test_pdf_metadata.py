from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from pdf_manager.core.pdf_metadata import extract_pdf_metadata

pytestmark = pytest.mark.unit


def test_pdf_metadata_extracts_basic_fields(sample_pdf_folder: Path) -> None:
    pdf_path = sample_pdf_folder / "sample.pdf"

    record = extract_pdf_metadata(pdf_path)

    assert record.file_name == "sample.pdf"
    assert record.full_path == str(pdf_path)
    assert record.parent_folder == str(sample_pdf_folder)
    assert record.file_size_bytes > 0
    assert record.created_date is not None
    assert record.modified_date is not None
    assert record.page_count == 1
    assert record.title == "Sample PDF"


def test_pdf_metadata_detects_invalid_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "invalid.pdf"
    pdf_path.write_text("not a valid pdf", encoding="utf-8")

    record = extract_pdf_metadata(pdf_path)

    assert record.error is not None
    assert record.text_extractable is False


def test_pdf_metadata_detects_encrypted_pdf_if_supported(
    tmp_path: Path, sample_pdf_factory: Callable[..., None]
) -> None:
    pdf_path = tmp_path / "encrypted.pdf"
    sample_pdf_factory(pdf_path, encrypted=True)

    record = extract_pdf_metadata(pdf_path)

    assert record.encrypted is True
    assert record.error is not None


def test_pdf_metadata_extracts_text_preview_when_available(tmp_path: Path, sample_pdf_factory: Callable[..., None]) -> None:
    pdf_path = tmp_path / "text.pdf"
    sample_pdf_factory(pdf_path, text="Hello preview text")

    record = extract_pdf_metadata(pdf_path)

    assert record.text_extractable is True
    assert record.text_preview is not None
    assert "Hello preview text" in record.text_preview
