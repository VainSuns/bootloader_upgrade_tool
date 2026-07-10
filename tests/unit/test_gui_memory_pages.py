import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QAbstractItemView, QLabel, QSplitter

from bootloader_upgrade_tool.gui.layout_metrics import (
    MEMORY_ADDRESS_COLUMN_WIDTH,
    MEMORY_DETAILS_MINIMUM_WIDTH,
    MEMORY_SPLITTER_HANDLE_WIDTH,
    MEMORY_SPLITTER_INITIAL_SIZES,
    MEMORY_TABLE_MINIMUM_WIDTH,
    MEMORY_WORD_COLUMNS,
    MEMORY_WORD_COLUMN_MINIMUM_WIDTH,
)
from bootloader_upgrade_tool.gui.pages import (
    MEMORY_DISPLAY_FORMATS,
    MEMORY_TABLE_HEADERS,
    MemoryTargetPage,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_memory_page_uses_shared_read_only_sixteen_word_layout() -> None:
    app = qt_app()
    page = MemoryTargetPage("cpu1")
    page.resize(1180, 680)
    page.show()
    app.processEvents()

    assert page.objectName() == "memoryCpu1Page"
    assert page.header.objectName() == "memoryCpu1PageHeader"
    assert page.interactions_enabled
    assert isinstance(page.horizontal_splitter, QSplitter)
    assert page.horizontal_splitter.objectName() == "memoryCpu1HorizontalSplitter"
    assert page.horizontal_splitter.orientation() == Qt.Orientation.Horizontal
    assert not page.horizontal_splitter.childrenCollapsible()
    assert page.horizontal_splitter.handleWidth() == MEMORY_SPLITTER_HANDLE_WIDTH
    assert page.table_card.minimumWidth() == MEMORY_TABLE_MINIMUM_WIDTH
    assert page.details_card.minimumWidth() == MEMORY_DETAILS_MINIMUM_WIDTH
    assert MEMORY_SPLITTER_INITIAL_SIZES == (90, 10)
    assert MEMORY_DETAILS_MINIMUM_WIDTH == 0
    assert not page.details_card.header.subtitle_label.isVisible()

    assert page.word_count_spin.minimum() == 1
    assert page.word_count_spin.maximum() == 4096
    assert page.word_count_spin.value() == 256
    assert tuple(page.display_format_combo.itemText(i) for i in range(page.display_format_combo.count())) == MEMORY_DISPLAY_FORMATS

    assert MEMORY_WORD_COLUMNS == 16
    assert page.memory_table.columnCount() == MEMORY_WORD_COLUMNS + 1
    assert tuple(
        page.memory_table.horizontalHeaderItem(i).text()
        for i in range(page.memory_table.columnCount())
    ) == MEMORY_TABLE_HEADERS
    assert MEMORY_TABLE_HEADERS[-1] == "+F"

    start_x = page.start_address_edit.mapTo(page, QPoint(0, 0)).x()
    search_x = page.search_edit.mapTo(page, QPoint(0, 0)).x()
    assert abs(start_x - search_x) <= 2

    # Top controls stay packed to the left; the flexible space is after Export.
    word_count_x = page.word_count_spin.mapTo(page, QPoint(0, 0)).x()
    display_format_x = page.display_format_combo.mapTo(page, QPoint(0, 0)).x()
    refresh_x = page.refresh_button.mapTo(page, QPoint(0, 0)).x()
    export_x = page.export_button.mapTo(page, QPoint(0, 0)).x()
    assert start_x < word_count_x < display_format_x < refresh_x < export_x
    assert export_x + page.export_button.width() < page.control_card.width()
    assert page.memory_table.columnWidth(0) == MEMORY_ADDRESS_COLUMN_WIDTH
    assert MEMORY_WORD_COLUMN_MINIMUM_WIDTH == 58
    assert all(
        page.memory_table.columnWidth(column) == MEMORY_WORD_COLUMN_MINIMUM_WIDTH
        for column in range(1, page.memory_table.columnCount())
    )

    assert page.memory_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert page.memory_table.rowCount() > 0
    assert "Preview Data" in page.preview_notice.text()
    assert not page.refresh_button.isEnabled()
    assert not page.export_button.isEnabled()

    page.memory_table.setCurrentCell(0, 3)
    app.processEvents()
    assert page.detail_values["offset"].text() == "+2"
    assert page.detail_values["hex16"].text().startswith("0x")

    visible_text = {label.text() for label in page.findChildren(QLabel)}
    assert not ({"Write", "Modify", "Commit", "Patch", "Fill"} & visible_text)

    page.close()
    app.processEvents()


def test_memory_unknown_words_render_question_marks_and_keep_address_context() -> None:
    app = qt_app()
    page = MemoryTargetPage("cpu1")
    page.resize(1180, 680)
    page.show()
    app.processEvents()

    page.set_memory_rows([(0x100, (0x1234, 0x5678))])
    app.processEvents()
    assert page.memory_table.item(0, 1).text() == "1234"
    assert page.memory_table.item(0, 2).text() == "5678"
    assert page.memory_table.item(0, 3).text() == "????"
    assert page.memory_table.item(0, 16).text() == "????"

    page.memory_table.setCurrentCell(0, 16)
    app.processEvents()
    assert page.detail_values["address"].text() == "0x00010F"
    assert page.detail_values["offset"].text() == "+F"
    assert page.detail_values["hex16"].text() == "????"
    assert page.detail_values["unsigned"].text() == "????"

    page.set_memory_rows([])
    app.processEvents()
    assert page.memory_table.rowCount() == 1
    assert all(
        page.memory_table.item(0, column).text() == "????"
        for column in range(1, MEMORY_WORD_COLUMNS + 1)
    )

    page.close()
    app.processEvents()


def test_cpu2_memory_page_is_visible_but_target_controls_are_disabled() -> None:
    app = qt_app()
    page = MemoryTargetPage("cpu2")
    page.show()
    app.processEvents()

    assert page.objectName() == "memoryCpu2Page"
    assert not page.interactions_enabled
    assert not page.start_address_edit.isEnabled()
    assert not page.word_count_spin.isEnabled()
    assert not page.display_format_combo.isEnabled()
    assert not page.search_edit.isEnabled()
    assert page.memory_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert page.memory_table.rowCount() > 0

    page.close()
    app.processEvents()


def test_memory_search_filters_only_loaded_local_rows() -> None:
    app = qt_app()
    page = MemoryTargetPage("cpu1")
    page.show()
    app.processEvents()

    page.search_edit.setText("ABCD")
    app.processEvents()
    assert not page.memory_table.isRowHidden(0)
    assert any(page.memory_table.isRowHidden(row) for row in range(1, page.memory_table.rowCount()))

    page.search_edit.clear()
    app.processEvents()
    assert all(not page.memory_table.isRowHidden(row) for row in range(page.memory_table.rowCount()))

    page.close()
    app.processEvents()
