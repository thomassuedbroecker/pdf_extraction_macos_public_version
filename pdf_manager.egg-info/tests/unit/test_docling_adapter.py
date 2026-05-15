from __future__ import annotations

import sys
import types
import builtins

import pytest

from pdf_manager.integrations.docling_adapter import DoclingAdapter
from pdf_manager.integrations import docling_adapter


pytestmark = pytest.mark.unit


def test_docling_adapter_extracts_markdown_when_docling_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDocument:
        def export_to_markdown(self) -> str:
            return "# Extracted\n\nText"

    class FakeResult:
        document = FakeDocument()

    class FakeDocumentConverter:
        def convert(self, path: str) -> FakeResult:
            assert path == "/tmp/report.pdf"
            return FakeResult()

    docling_module = types.ModuleType("docling")
    converter_module = types.ModuleType("docling.document_converter")
    converter_module.DocumentConverter = FakeDocumentConverter

    monkeypatch.setitem(sys.modules, "docling", docling_module)
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter_module)

    text = DoclingAdapter().extract_text("/tmp/report.pdf")

    assert text == "# Extracted\n\nText"


def test_docling_adapter_reports_missing_docling(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "docling.document_converter":
            raise ImportError("No module named docling")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="Docling is not installed"):
        DoclingAdapter().extract_text("/tmp/report.pdf")
