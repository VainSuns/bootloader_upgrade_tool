import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QWidget,
)

from bootloader_upgrade_tool.gui.pages import (
    ADVANCED_TAB_LABELS,
    ERASE_SCOPE_LABELS,
    AdvancedPage,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_advanced_page_uses_frozen_vertical_splitter_and_tabs() -> None:
    app = qt_app()
    page = AdvancedPage()
    page.resize(1180, 680)
    page.show()
    app.processEvents()

    assert page.objectName() == "advancedPage"
    assert page.header.objectName() == "advancedPageHeader"
    assert isinstance(page.vertical_splitter, QSplitter)
    assert page.vertical_splitter.objectName() == "advancedVerticalSplitter"
    assert page.vertical_splitter.orientation() == Qt.Orientation.Vertical
    assert not page.vertical_splitter.childrenCollapsible()

    assert isinstance(page.tabs, QTabWidget)
    assert page.tabs.objectName() == "advancedTabs"
    assert tuple(page.tabs.tabText(index) for index in range(page.tabs.count())) == (
        ADVANCED_TAB_LABELS
    )
    assert page.tabs.currentIndex() == 0

    assert page.result_card.objectName() == "advancedSharedResultCard"
    assert isinstance(page.result_output, QPlainTextEdit)
    assert page.result_output.isReadOnly()
    assert page.result_output.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap
    assert "No diagnostic" in page.result_output.toPlainText()

    # Advanced content must use the full available page width rather than a
    # centered maximum-width host.
    assert page.content_container.maximumWidth() > 1_000_000
    root_layout = page.layout()
    content_index = root_layout.indexOf(page.content_container)
    assert content_index >= 0
    content_item = root_layout.itemAt(content_index)
    assert content_item is not None
    assert content_item.alignment() == Qt.AlignmentFlag(0)
    assert abs(page.content_container.width() - page.header.width()) <= 2

    page.close()
    app.processEvents()


def test_ram_controls_emit_intent_without_changing_layout() -> None:
    page = AdvancedPage()
    emitted = []
    page.cpu1RamBrowseRequested.connect(lambda: emitted.append("browse1"))
    page.cpu2RamBrowseRequested.connect(lambda: emitted.append("browse2"))
    page.ramLoadRequested.connect(lambda: emitted.append("load"))
    page.ramCheckCrcRequested.connect(lambda: emitted.append("crc"))
    page.ramRunRequested.connect(lambda: emitted.append("run"))
    page.set_ram_controls_enabled(cpu1_browse=True, cpu2_browse=True, load=True, check_crc=True, run=True)
    for button in (page.cpu1_ram_browse_button, page.cpu2_ram_browse_button, page.ram_load_button, page.ram_crc_button, page.ram_run_button):
        button.click()
    assert emitted == ["browse1", "browse2", "load", "crc", "run"]


def test_flash_tab_has_only_approved_scopes_and_operations() -> None:
    app = qt_app()
    page = AdvancedPage()

    assert tuple(
        page.erase_scope_combo.itemText(index)
        for index in range(page.erase_scope_combo.count())
    ) == ERASE_SCOPE_LABELS
    assert "Entire Flash" not in [
        page.erase_scope_combo.itemText(index)
        for index in range(page.erase_scope_combo.count())
    ]

    buttons = {
        button.text(): button
        for button in (
            page.erase_button,
            page.program_only_button,
            page.verify_only_button,
        )
    }
    assert set(buttons) == {"Erase", "Program Only", "Verify Only"}
    assert all(not button.isEnabled() for button in buttons.values())
    assert "SERVICE_ATTACH" not in buttons

    visible_text = [label.text() for label in page.flash_tab.findChildren(QLabel)]
    assert any("Sector A is always protected" in text for text in visible_text)
    assert any(
        "Verify Only performs verification only; it does not write IMAGE_VALID"
        in text
        for text in visible_text
    )

    assert page.custom_sector_mask_edit.isReadOnly()
    assert not page.custom_sector_selector.isEnabled()
    page.erase_scope_combo.setCurrentText("Custom Sector Mask")
    assert page.custom_sector_selector.isEnabled()
    assert page.custom_sector_mask_edit.isEnabled()
    assert page.custom_sector_mask_button.isEnabled()

    page.custom_sector_selector.set_selected_sector_ids(("B", "C", "D"))
    assert page.custom_sector_selector.selected_sector_ids() == ("B", "C", "D")
    assert page.custom_sector_selector.selected_mask() == 0x0000000E
    assert "B, C, D" in page.custom_sector_mask_edit.text()
    assert "0x0000000E" in page.custom_sector_mask_edit.text()

    page.close()
    app.processEvents()


def test_flash_uses_two_image_panels_with_independent_two_by_two_summaries() -> None:
    app = qt_app()
    page = AdvancedPage()
    page.resize(1440, 900)
    page.tabs.setCurrentWidget(page.flash_tab)
    page.show()
    app.processEvents()

    assert page.flash_image_edit is page.cpu1_flash_image_edit
    assert page.flash_browse_button is page.cpu1_flash_browse_button
    assert page.flash_image_summary_grid is page.cpu1_flash_image_summary_grid
    assert page.cpu1_flash_image_edit is not page.cpu2_flash_image_edit

    cpu1_panel = page.cpu1_flash_image_panel
    cpu2_panel = page.cpu2_flash_image_panel
    assert abs(cpu1_panel.geometry().top() - cpu2_panel.geometry().top()) <= 2
    assert cpu1_panel.geometry().right() < cpu2_panel.geometry().left()
    assert abs(cpu1_panel.width() - cpu2_panel.width()) <= 2

    assert page.cpu1_flash_image_summary_grid.parentWidget() is cpu1_panel
    assert page.cpu2_flash_image_summary_grid.parentWidget() is cpu2_panel

    page.set_cpu1_flash_image_summary(
        target="CPU1 / TMS320F28377D",
        entry_point="0x082400",
        image_size="96 KiB",
        crc32="0x7A4C2D91",
    )
    page.set_cpu2_flash_image_summary(
        target="CPU2 / TMS320F28377D",
        entry_point="0x092400",
        image_size="80 KiB",
        crc32="0x29B638A4",
    )

    assert [
        page.cpu1_flash_target_value.text(),
        page.cpu1_flash_entry_point_value.text(),
        page.cpu1_flash_image_size_value.text(),
        page.cpu1_flash_crc32_value.text(),
    ] == [
        "CPU1 / TMS320F28377D",
        "0x082400",
        "96 KiB",
        "0x7A4C2D91",
    ]
    assert [
        page.cpu2_flash_target_value.text(),
        page.cpu2_flash_entry_point_value.text(),
        page.cpu2_flash_image_size_value.text(),
        page.cpu2_flash_crc32_value.text(),
    ] == [
        "CPU2 / TMS320F28377D",
        "0x092400",
        "80 KiB",
        "0x29B638A4",
    ]

    _assert_two_by_two_summary_grid(
        page.cpu1_flash_target_value,
        page.cpu1_flash_entry_point_value,
        page.cpu1_flash_image_size_value,
        page.cpu1_flash_crc32_value,
    )
    _assert_two_by_two_summary_grid(
        page.cpu2_flash_target_value,
        page.cpu2_flash_entry_point_value,
        page.cpu2_flash_image_size_value,
        page.cpu2_flash_crc32_value,
    )

    page.close()
    app.processEvents()


def test_diagnostics_and_metadata_actions_follow_operation_ownership() -> None:
    app = qt_app()
    page = AdvancedPage()

    diagnostics_buttons = {
        button.text(): button
        for button in page.diagnostics_tab.findChildren(QPushButton)
    }
    assert diagnostics_buttons == {
        "Read Device Info": page.read_device_info_button,
        "Read Protocol Info": page.read_protocol_info_button,
        "Get Last Error": page.get_last_error_button,
    }
    assert "Refresh Status" not in diagnostics_buttons

    metadata_action_host = page.findChild(QWidget, "advancedMetadataActionRow")
    assert metadata_action_host is not None
    action_layout = metadata_action_host.layout()
    metadata_button_order = [
        item.widget().text()
        for index in range(action_layout.count())
        if (item := action_layout.itemAt(index)).widget() is not None
        and isinstance(item.widget(), QPushButton)
    ]
    assert metadata_button_order == [
        "Refresh Status",
        "Write IMAGE_VALID",
        "Write BOOT_ATTEMPT",
        "Write APP_CONFIRMED",
    ]
    assert page.refresh_status_button in page.metadata_tab.findChildren(QPushButton)
    assert all(
        not button.isEnabled()
        for button in (
            page.refresh_status_button,
            page.write_image_valid_button,
            page.write_boot_attempt_button,
            page.write_app_confirmed_button,
        )
    )

    assert not page.run_flash_app_button.isEnabled()
    assert not page.reset_target_button.isEnabled()
    assert page.reset_target_button.text() == "Reset Target"

    ram_buttons = {
        button.text(): button
        for button in page.ram_image_tab.findChildren(QPushButton)
    }
    assert ram_buttons == {
        "Load": page.ram_load_button,
        "Check CRC": page.ram_crc_button,
        "Run": page.ram_run_button,
    }
    assert all(not button.isEnabled() for button in ram_buttons.values())

    for browse_button in (
        page.cpu1_flash_browse_button,
        page.cpu2_flash_browse_button,
        page.cpu1_ram_browse_button,
        page.cpu2_ram_browse_button,
    ):
        assert browse_button.text() == ""
        assert browse_button.width() >= 40
        assert browse_button.toolButtonStyle() == (
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        assert browse_button.property("variant") == "secondary"
        assert browse_button.property("filePickerButton") is True
        assert not browse_button.isEnabled()

    ram_text = [label.text() for label in page.ram_image_tab.findChildren(QLabel)]
    assert any("currently connected target" in text for text in ram_text)
    assert any("RUN_RAM / RAM_RUN" in text for text in ram_text)

    page.close()
    app.processEvents()


def test_metadata_summary_uses_aligned_three_by_two_grid() -> None:
    app = qt_app()
    page = AdvancedPage()
    page.resize(1440, 900)
    page.tabs.setCurrentWidget(page.metadata_tab)
    page.show()
    app.processEvents()

    summary_host = page.findChild(QWidget, "advancedMetadataSummaryGrid")
    assert summary_host is not None
    grid = summary_host.layout()
    assert grid is not None

    expected = (
        (0, 0, "advancedMetadataMetadataValidRow", "Metadata Valid"),
        (0, 1, "advancedMetadataImageValidRow", "IMAGE_VALID"),
        (1, 0, "advancedMetadataFlashAppCrc32Row", "Flash App CRC32"),
        (1, 1, "advancedMetadataBootAttemptRow", "BOOT_ATTEMPT"),
        (2, 0, "advancedMetadataEntryPointRow", "Entry Point"),
        (2, 1, "advancedMetadataAppConfirmedRow", "APP_CONFIRMED"),
    )

    actual = []
    for index in range(grid.count()):
        item = grid.itemAt(index)
        widget = item.widget()
        assert widget is not None
        row, column, row_span, column_span = grid.getItemPosition(index)
        assert row_span == 1
        assert column_span == 1
        label = widget.layout().itemAt(0).widget()
        actual.append((row, column, widget.objectName(), label.text()))

    assert tuple(actual) == expected
    assert grid.columnStretch(0) == grid.columnStretch(1) == 1

    left_rows = [grid.itemAtPosition(row, 0).widget() for row in range(3)]
    right_rows = [grid.itemAtPosition(row, 1).widget() for row in range(3)]
    assert all(widget is not None for widget in left_rows + right_rows)
    assert max(widget.width() for widget in left_rows) - min(
        widget.width() for widget in left_rows
    ) <= 2
    assert max(widget.width() for widget in right_rows) - min(
        widget.width() for widget in right_rows
    ) <= 2
    assert abs(left_rows[0].width() - right_rows[0].width()) <= 2

    page.close()
    app.processEvents()


def test_read_only_buttons_emit_only_explicit_signals() -> None:
    app = qt_app()
    page = AdvancedPage()
    emitted = []
    page.readDeviceInfoRequested.connect(lambda: emitted.append("device"))
    page.readProtocolInfoRequested.connect(lambda: emitted.append("protocol"))
    page.readLastErrorRequested.connect(lambda: emitted.append("error"))
    page.refreshMetadataRequested.connect(lambda: emitted.append("metadata"))
    page.set_read_only_controls_enabled(
        device_info=True,
        protocol_info=True,
        last_error=True,
        metadata=True,
    )
    for button in (
        page.read_device_info_button,
        page.read_protocol_info_button,
        page.get_last_error_button,
        page.refresh_status_button,
    ):
        button.click()
    assert emitted == ["device", "protocol", "error", "metadata"]
    assert not hasattr(page, "statusRequested")
    page.close()
    app.processEvents()


def test_ram_uses_two_image_panels_with_independent_summaries_and_one_operation_group() -> None:
    app = qt_app()
    page = AdvancedPage()
    page.resize(1440, 900)
    page.tabs.setCurrentWidget(page.ram_image_tab)
    page.show()
    app.processEvents()

    cpu1_panel = page.cpu1_ram_image_panel
    cpu2_panel = page.cpu2_ram_image_panel
    assert abs(cpu1_panel.geometry().top() - cpu2_panel.geometry().top()) <= 2
    assert cpu1_panel.geometry().right() < cpu2_panel.geometry().left()
    assert abs(cpu1_panel.width() - cpu2_panel.width()) <= 2
    assert page.cpu1_ram_image_edit.width() >= 250
    assert page.cpu2_ram_image_edit.width() >= 250

    assert page.cpu1_ram_image_summary_grid.parentWidget() is cpu1_panel
    assert page.cpu2_ram_image_summary_grid.parentWidget() is cpu2_panel

    page.set_cpu1_ram_image_summary(
        target="CPU1 / TMS320F28377D",
        entry_point="RAM CPU1 entry",
        image_size="24 KiB",
        crc32="0x19A4E2C7",
    )
    page.set_cpu2_ram_image_summary(
        target="CPU2 / TMS320F28377D",
        entry_point="RAM CPU2 entry",
        image_size="20 KiB",
        crc32="0xC236D8A1",
    )

    assert [
        page.cpu1_ram_target_value.text(),
        page.cpu1_ram_entry_point_value.text(),
        page.cpu1_ram_image_size_value.text(),
        page.cpu1_ram_crc32_value.text(),
    ] == [
        "CPU1 / TMS320F28377D",
        "RAM CPU1 entry",
        "24 KiB",
        "0x19A4E2C7",
    ]
    assert [
        page.cpu2_ram_target_value.text(),
        page.cpu2_ram_entry_point_value.text(),
        page.cpu2_ram_image_size_value.text(),
        page.cpu2_ram_crc32_value.text(),
    ] == [
        "CPU2 / TMS320F28377D",
        "RAM CPU2 entry",
        "20 KiB",
        "0xC236D8A1",
    ]

    _assert_two_by_two_summary_grid(
        page.cpu1_ram_target_value,
        page.cpu1_ram_entry_point_value,
        page.cpu1_ram_image_size_value,
        page.cpu1_ram_crc32_value,
    )
    _assert_two_by_two_summary_grid(
        page.cpu2_ram_target_value,
        page.cpu2_ram_entry_point_value,
        page.cpu2_ram_image_size_value,
        page.cpu2_ram_crc32_value,
    )

    operation_card = page.findChild(QWidget, "advancedRamOperationsCard")
    assert operation_card is not None
    image_card = page.findChild(QWidget, "advancedRamImageCard")
    assert image_card is not None
    assert operation_card.mapTo(page, operation_card.rect().topLeft()).y() > image_card.mapTo(
        page, image_card.rect().bottomLeft()
    ).y()

    page.close()
    app.processEvents()


def test_execution_actions_align_with_entry_point_editor() -> None:
    app = qt_app()
    page = AdvancedPage()
    page.resize(1440, 900)
    page.tabs.setCurrentWidget(page.execution_tab)
    page.show()
    app.processEvents()

    entry_row = page.findChild(QWidget, "advancedExecutionEntryPointRow")
    action_row = page.findChild(QWidget, "advancedExecutionActionRow")
    assert entry_row is not None
    assert action_row is not None
    editor_left = page.execution_entry_point.mapTo(
        page, page.execution_entry_point.rect().topLeft()
    ).x()
    button_left = page.run_flash_app_button.mapTo(
        page, page.run_flash_app_button.rect().topLeft()
    ).x()
    assert abs(editor_left - button_left) <= 2

    page.close()
    app.processEvents()



def test_per_cpu_image_summary_content_uses_compact_left_alignment() -> None:
    app = qt_app()
    page = AdvancedPage()
    page.resize(1440, 900)
    page.show()
    app.processEvents()

    summary_values = (
        page.cpu1_flash_target_value,
        page.cpu1_flash_entry_point_value,
        page.cpu1_flash_image_size_value,
        page.cpu1_flash_crc32_value,
        page.cpu2_flash_target_value,
        page.cpu2_flash_entry_point_value,
        page.cpu2_flash_image_size_value,
        page.cpu2_flash_crc32_value,
        page.cpu1_ram_target_value,
        page.cpu1_ram_entry_point_value,
        page.cpu1_ram_image_size_value,
        page.cpu1_ram_crc32_value,
        page.cpu2_ram_target_value,
        page.cpu2_ram_entry_point_value,
        page.cpu2_ram_image_size_value,
        page.cpu2_ram_crc32_value,
    )
    for value in summary_values:
        host = value.parentWidget()
        labels = [label for label in host.findChildren(QLabel) if label is not value]
        assert len(labels) == 1
        label = labels[0]
        assert label.width() <= 100
        assert value.geometry().left() <= 110

    page.close()
    app.processEvents()

def test_advanced_object_names_are_unique() -> None:
    app = qt_app()
    page = AdvancedPage()
    names = [
        widget.objectName()
        for widget in page.findChildren(QWidget)
        if widget.objectName().startswith("advanced")
    ]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert duplicates == []

    page.close()
    app.processEvents()


def _assert_two_by_two_summary_grid(
    top_left: QLabel,
    top_right: QLabel,
    bottom_left: QLabel,
    bottom_right: QLabel,
) -> None:
    top_left_host = top_left.parentWidget()
    top_right_host = top_right.parentWidget()
    bottom_left_host = bottom_left.parentWidget()
    bottom_right_host = bottom_right.parentWidget()

    assert abs(top_left_host.geometry().top() - top_right_host.geometry().top()) <= 2
    assert abs(bottom_left_host.geometry().top() - bottom_right_host.geometry().top()) <= 2
    assert bottom_left_host.geometry().top() > top_left_host.geometry().bottom()
    assert bottom_right_host.geometry().top() > top_right_host.geometry().bottom()
    assert abs(top_left_host.geometry().left() - bottom_left_host.geometry().left()) <= 2
    assert abs(top_right_host.geometry().left() - bottom_right_host.geometry().left()) <= 2
    assert top_left_host.geometry().right() < top_right_host.geometry().left()
    assert bottom_left_host.geometry().right() < bottom_right_host.geometry().left()
