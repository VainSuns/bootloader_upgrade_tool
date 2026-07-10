import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QAbstractItemView, QPlainTextEdit, QSplitter

from bootloader_upgrade_tool.gui.pages import LOG_LEVEL_CHOICES, LOG_TABLE_HEADERS, LogsPage


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_logs_page_is_structured_history_separate_from_console() -> None:
    app = qt_app()
    page = LogsPage()
    page.resize(1180, 680)
    page.show()
    app.processEvents()

    assert page.objectName() == "logsPage"
    assert page.header.objectName() == "logsPageHeader"
    assert page.filter_bar.objectName() == "logsFilterBar"
    assert isinstance(page.horizontal_splitter, QSplitter)
    assert page.horizontal_splitter.objectName() == "logsHorizontalSplitter"
    assert page.horizontal_splitter.orientation() == Qt.Orientation.Horizontal
    assert not page.horizontal_splitter.childrenCollapsible()

    assert tuple(page.level_combo.itemText(i) for i in range(page.level_combo.count())) == LOG_LEVEL_CHOICES
    assert tuple(
        page.logs_table.horizontalHeaderItem(i).text()
        for i in range(page.logs_table.columnCount())
    ) == LOG_TABLE_HEADERS
    assert "Stage" not in LOG_TABLE_HEADERS
    assert page.logs_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert page.logs_table.rowCount() == 3
    assert "Preview Data" in page.preview_notice.text()

    assert not page.export_button.isEnabled()
    assert not page.open_folder_button.isEnabled()
    assert page.reset_filter_button.isEnabled()
    assert page.clear_logs_button.isEnabled()
    assert page.findChild(QPlainTextEdit, "consoleOutput") is None
    assert page.detail_message.objectName() == "logsDetailMessage"

    page.logs_table.selectRow(1)
    app.processEvents()
    assert page.detail_values["stage"].text() == "Not executed"
    assert "Descriptor address" in page.detail_message.toPlainText()

    page.close()
    app.processEvents()


def test_logs_filters_and_clear_are_local_only() -> None:
    app = qt_app()
    page = LogsPage()
    page.show()
    app.processEvents()

    page.level_combo.setCurrentText("Warning")
    app.processEvents()
    visible_rows = [
        row for row in range(page.logs_table.rowCount()) if not page.logs_table.isRowHidden(row)
    ]
    assert visible_rows == [2]

    page.reset_filter_button.click()
    app.processEvents()
    assert page.level_combo.currentText() == "All"
    assert all(not page.logs_table.isRowHidden(row) for row in range(page.logs_table.rowCount()))

    page.clear_logs_button.click()
    app.processEvents()
    assert page.logs_table.rowCount() == 0
    assert page.detail_message.toPlainText() == ""

    page.close()
    app.processEvents()
