"""Small Qt widget for PDF page-count and file-size distributions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from pdf_manager.models.pdf_record import PdfRecord


@dataclass(slots=True)
class DistributionBin:
    """One histogram bucket."""

    label: str
    count: int


class DistributionChartWidget(QWidget):
    """Paints compact histograms for pages and file sizes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.records: list[PdfRecord] = []
        self.page_bins: list[DistributionBin] = []
        self.size_bins: list[DistributionBin] = []
        self.setMinimumHeight(150)

    def set_records(self, records: list[PdfRecord]) -> None:
        """Update the chart data and schedule a repaint."""
        self.records = records
        self.page_bins = self._page_distribution(records)
        self.size_bins = self._size_distribution(records)
        self.update()

    @staticmethod
    def _page_distribution(records: list[PdfRecord]) -> list[DistributionBin]:
        buckets = [
            ("0", lambda value: value == 0),
            ("1", lambda value: value == 1),
            ("2-5", lambda value: 2 <= value <= 5),
            ("6-10", lambda value: 6 <= value <= 10),
            ("11-50", lambda value: 11 <= value <= 50),
            ("51-100", lambda value: 51 <= value <= 100),
            (">100", lambda value: value > 100),
        ]
        return _count_bins([record.page_count or 0 for record in records], buckets)

    @staticmethod
    def _size_distribution(records: list[PdfRecord]) -> list[DistributionBin]:
        buckets = [
            ("<1 MiB", lambda value: value < 1),
            ("1-5", lambda value: 1 <= value < 5),
            ("5-10", lambda value: 5 <= value < 10),
            ("10-50", lambda value: 10 <= value < 50),
            ("50-100", lambda value: 50 <= value < 100),
            (">=100", lambda value: value >= 100),
        ]
        return _count_bins([record.file_size_mb for record in records], buckets)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        content = self.rect().adjusted(12, 10, -12, -10)
        gap = 16
        chart_width = (content.width() - gap) / 2
        page_rect = QRectF(content.left(), content.top(), chart_width, content.height())
        size_rect = QRectF(page_rect.right() + gap, content.top(), chart_width, content.height())

        self._draw_histogram(painter, page_rect, "Pages", self.page_bins, QColor("#4C78A8"))
        self._draw_histogram(painter, size_rect, "File size", self.size_bins, QColor("#F58518"))
        painter.end()

    def _draw_histogram(
        self,
        painter: QPainter,
        rect: QRectF,
        title: str,
        bins: list[DistributionBin],
        color: QColor,
    ) -> None:
        painter.setPen(QPen(QColor("#202124")))
        painter.drawText(rect.left(), rect.top() + 14, title)

        if not bins or sum(item.count for item in bins) == 0:
            painter.setPen(QPen(QColor("#6b7280")))
            painter.drawText(rect.adjusted(0, 28, 0, 0), Qt.AlignLeft | Qt.AlignTop, "No visible PDF records")
            return

        plot = rect.adjusted(0, 28, 0, -20)
        max_count = max(item.count for item in bins) or 1
        bar_gap = 4
        bar_width = max((plot.width() - bar_gap * (len(bins) - 1)) / len(bins), 4)
        painter.setPen(QPen(QColor("#d1d5db")))
        painter.drawLine(plot.bottomLeft(), plot.bottomRight())

        for index, item in enumerate(bins):
            x = plot.left() + index * (bar_width + bar_gap)
            height = 0 if item.count == 0 else max((item.count / max_count) * (plot.height() - 22), 2)
            bar = QRectF(x, plot.bottom() - height, bar_width, height)
            painter.fillRect(bar, color)
            painter.setPen(QPen(QColor("#202124")))
            painter.drawText(QRectF(x, bar.top() - 16, bar_width, 14), Qt.AlignCenter, str(item.count))
            painter.setPen(QPen(QColor("#4b5563")))
            painter.drawText(QRectF(x, plot.bottom() + 2, bar_width, 16), Qt.AlignCenter, item.label)


def _count_bins(values: list[float], buckets: list[tuple[str, Callable[[float], bool]]]) -> list[DistributionBin]:
    bins: list[DistributionBin] = []
    for label, predicate in buckets:
        count = sum(1 for value in values if predicate(value))
        bins.append(DistributionBin(label=label, count=count))
    return bins
