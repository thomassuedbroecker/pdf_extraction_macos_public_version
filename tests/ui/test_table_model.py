from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pdf_manager.models.pdf_record import PdfRecord
from pdf_manager.ui.distribution_chart import DistributionChartWidget
from pdf_manager.ui.table_model import PdfFilterProxyModel, PdfTableModel

pytestmark = pytest.mark.ui


@pytest.fixture
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_table_model_exposes_pdf_records(qt_app: QApplication, sample_pdf_records: list[PdfRecord]) -> None:
    model = PdfTableModel(["file_name", "page_count", "title"])
    model.set_records(sample_pdf_records)

    assert model.rowCount() == 2
    assert model.columnCount() == 3
    assert model.index(0, 0).data(Qt.DisplayRole) == "alpha.pdf"
    assert model.index(1, 2).data(Qt.DisplayRole) == "Beta"


def test_table_model_sorts_records_by_column(qt_app: QApplication, sample_pdf_records: list[PdfRecord]) -> None:
    model = PdfTableModel(["file_name", "page_count"])
    model.set_records(list(reversed(sample_pdf_records)))
    proxy = PdfFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.sort(0, Qt.AscendingOrder)

    assert proxy.index(0, 0).data(Qt.DisplayRole) == "alpha.pdf"
    assert proxy.index(1, 0).data(Qt.DisplayRole) == "beta.pdf"


def test_table_model_filters_records(qt_app: QApplication, sample_pdf_records: list[PdfRecord]) -> None:
    model = PdfTableModel(["file_name", "title", "text_preview"])
    model.set_records(sample_pdf_records)
    proxy = PdfFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_search_text("Alpha preview")

    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data(Qt.DisplayRole) == "alpha.pdf"


def test_distribution_chart_builds_page_and_size_bins(
    qt_app: QApplication, sample_pdf_records: list[PdfRecord]
) -> None:
    chart = DistributionChartWidget()

    chart.set_records(sample_pdf_records)

    assert sum(item.count for item in chart.page_bins) == 2
    assert sum(item.count for item in chart.size_bins) == 2
    assert next(item.count for item in chart.page_bins if item.label == "1") == 1
    assert next(item.count for item in chart.page_bins if item.label == "2-5") == 1
    assert next(item.count for item in chart.size_bins if item.label == "<1 MiB") == 2
