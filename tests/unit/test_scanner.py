from __future__ import annotations

from pathlib import Path

import pytest

from pdf_manager.core.scanner import PdfScanner

pytestmark = pytest.mark.unit


def test_scanner_finds_pdf_files_recursively(nested_pdf_folder: Path) -> None:
    records = PdfScanner().scan([nested_pdf_folder])

    assert {record.file_name for record in records} == {"root.pdf", "child.pdf"}


def test_scanner_ignores_non_pdf_files(non_pdf_folder: Path) -> None:
    records = PdfScanner().scan([non_pdf_folder])

    assert records == []


def test_scanner_handles_empty_folder(tmp_path: Path) -> None:
    records = PdfScanner().scan([tmp_path])

    assert records == []


def test_scanner_handles_permission_or_missing_folder_gracefully(tmp_path: Path) -> None:
    records = PdfScanner().scan([tmp_path / "does-not-exist"])

    assert records == []


def test_scanner_finds_uppercase_pdf_extensions(tmp_path: Path, sample_pdf_factory) -> None:
    pdf_path = tmp_path / "UPPER.PDF"
    sample_pdf_factory(pdf_path)

    records = PdfScanner().scan([tmp_path])

    assert [record.file_name for record in records] == ["UPPER.PDF"]


def test_scanner_continues_when_directory_walk_reports_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good_pdf = tmp_path / "good.pdf"
    good_pdf.write_text("not parsed in discover", encoding="utf-8")

    def fake_walk(root, topdown=True, onerror=None, followlinks=False):
        if onerror:
            onerror(PermissionError("denied"))
        yield str(tmp_path), [], ["good.pdf"]

    monkeypatch.setattr("pdf_manager.core.scanner.os.walk", fake_walk)

    paths = PdfScanner().discover([tmp_path])

    assert paths == [good_pdf.resolve()]
