"""Qt table model and filtering for PDF records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt

from pdf_manager.core.export_excel import COLUMN_LABELS
from pdf_manager.models.pdf_record import PdfRecord

DEFAULT_COLUMNS = [
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


class PdfTableModel(QAbstractTableModel):
    """Table model exposing PdfRecord objects."""

    def __init__(self, columns: list[str] | None = None) -> None:
        super().__init__()
        self.columns = columns or DEFAULT_COLUMNS.copy()
        self.records: list[PdfRecord] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        record = self.records[index.row()]
        column = self.columns[index.column()]
        value = self._raw_value(record, column)

        if role == Qt.DisplayRole:
            return self._display_value(value, column)
        if role == Qt.UserRole:
            return value
        if role == Qt.ToolTipRole and column in {"full_path", "text_preview", "error"}:
            return self._display_value(value, column)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return COLUMN_LABELS.get(self.columns[section], self.columns[section])
        return section + 1

    def add_record(self, record: PdfRecord) -> None:
        """Append a record to the model."""
        row = len(self.records)
        self.beginInsertRows(QModelIndex(), row, row)
        self.records.append(record)
        self.endInsertRows()

    def set_records(self, records: list[PdfRecord]) -> None:
        """Replace all records in the model."""
        self.beginResetModel()
        self.records = records
        self.endResetModel()

    def clear(self) -> None:
        """Remove all records."""
        self.set_records([])

    def record_at(self, source_row: int) -> PdfRecord | None:
        """Return a record by source row."""
        if 0 <= source_row < len(self.records):
            return self.records[source_row]
        return None

    def set_columns(self, columns: list[str]) -> None:
        """Set visible/exported columns."""
        self.beginResetModel()
        self.columns = columns
        self.endResetModel()

    @staticmethod
    def _raw_value(record: PdfRecord, column: str) -> Any:
        if column == "file_size_mb":
            return record.file_size_mb
        return getattr(record, column, None)

    @staticmethod
    def _display_value(value: Any, column: str) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat(sep=" ", timespec="seconds")
        if column == "file_size_mb":
            return f"{float(value):.2f}"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value)


class PdfFilterProxyModel(QSortFilterProxyModel):
    """Search and structured filters for PDF records."""

    def __init__(self) -> None:
        super().__init__()
        self.search_text = ""
        self.folder = ""
        self.min_pages: int | None = None
        self.max_pages: int | None = None
        self.min_size_mb: float | None = None
        self.max_size_mb: float | None = None
        self.encrypted: bool | None = None
        self.text_extractable: bool | None = None
        self.setSortRole(Qt.UserRole)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_value = left.data(Qt.UserRole)
        right_value = right.data(Qt.UserRole)
        if left_value is None:
            return right_value is not None
        if right_value is None:
            return False
        return left_value < right_value

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if not isinstance(model, PdfTableModel):
            return True
        record = model.record_at(source_row)
        if record is None:
            return False

        if self.folder and record.parent_folder != self.folder:
            return False
        if self.min_pages is not None and (record.page_count is None or record.page_count < self.min_pages):
            return False
        if self.max_pages is not None and (record.page_count is None or record.page_count > self.max_pages):
            return False
        if self.min_size_mb is not None and record.file_size_mb < self.min_size_mb:
            return False
        if self.max_size_mb is not None and record.file_size_mb > self.max_size_mb:
            return False
        if self.encrypted is not None and record.encrypted is not self.encrypted:
            return False
        if self.text_extractable is not None and record.text_extractable is not self.text_extractable:
            return False

        if self.search_text:
            haystack = " ".join(
                str(value or "")
                for value in [
                    record.file_name,
                    record.full_path,
                    record.title,
                    record.author,
                    record.subject,
                    record.producer,
                    record.text_preview,
                    record.error,
                ]
            ).lower()
            return self.search_text.lower() in haystack
        return True

    def set_search_text(self, value: str) -> None:
        self.search_text = value.strip()
        self.invalidateFilter()

    def set_folder(self, value: str) -> None:
        self.folder = value
        self.invalidateFilter()

    def set_page_range(self, minimum: int | None, maximum: int | None) -> None:
        self.min_pages = minimum
        self.max_pages = maximum
        self.invalidateFilter()

    def set_size_range(self, minimum: float | None, maximum: float | None) -> None:
        self.min_size_mb = minimum
        self.max_size_mb = maximum
        self.invalidateFilter()

    def set_encrypted_filter(self, value: bool | None) -> None:
        self.encrypted = value
        self.invalidateFilter()

    def set_text_extractable_filter(self, value: bool | None) -> None:
        self.text_extractable = value
        self.invalidateFilter()
