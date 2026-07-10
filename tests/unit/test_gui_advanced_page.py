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



def test_flash_image_summary_is_one_horizontal_row() -> None:
    app = qt_app()
    page = AdvancedPage()
    page.resize(1440, 900)
    page.tabs.setCurrentWidget(page.flash_tab)
    page.show()
    app.processEvents()

    page.set_flash_image_summary(
        target="CPU1 / TMS320F28377D",
        entry_point="0x082000",
        image_size="96 KiB",
        crc32="0x7A4C2D91",
    )
    values = (
        page.flash_target_value,
        page.flash_entry_point_value,
        page.flash_image_size_value,
        page.flash_crc32_value,
    )
    assert [value.text() for value in values] == [
        "CPU1 / TMS320F28377D",
        "0x082000",
        "96 KiB",
        "0x7A4C2D91",
    ]
    tops = [value.parentWidget().geometry().top() for value in values]
    assert max(tops) - min(tops) <= 2
    for previous, current in zip(values, values[1:]):
        assert previous.parentWidget().geometry().right() < current.parentWidget().geometry().left()

    page.close()
    app.processEvents()

def test_metadata_execution_and_ram_actions_are_separate_disabled_controls() -> None:
    app = qt_app()
    page = AdvancedPage()

    metadata_buttons = {
        button.text(): button
        for button in page.metadata_tab.findChildren(QPushButton)
    }
    assert set(metadata_buttons) == {
        "Write IMAGE_VALID",
        "Write BOOT_ATTEMPT",
        "Write APP_CONFIRMED",
    }
    assert all(not button.isEnabled() for button in metadata_buttons.values())

    assert not page.run_flash_app_button.isEnabled()
    assert not page.reset_target_button.isEnabled()
    assert page.reset_target_button.text() == "Reset Target"

    assert page.cpu1_ram_card.isEnabled()
    assert not page.cpu2_ram_card.isEnabled()
    for button in (
        page.cpu1_ram_load_button,
        page.cpu1_ram_crc_button,
        page.cpu1_ram_run_button,
        page.cpu2_ram_load_button,
        page.cpu2_ram_crc_button,
        page.cpu2_ram_run_button,
    ):
        assert not button.isEnabled()

    for browse_button in (
        page.flash_browse_button,
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

    ram_text = [label.text() for label in page.ram_image_tab.findChildren(QLabel)]
    assert any("RUN_RAM / RAM_RUN" in text for text in ram_text)

    page.close()
    app.processEvents()


def test_ram_path_rows_align_with_action_rows_and_use_available_width() -> None:
    app = qt_app()
    page = AdvancedPage()
    page.resize(1440, 900)
    page.tabs.setCurrentWidget(page.ram_image_tab)
    page.show()
    app.processEvents()

    for path_host, action_host, image_edit, browse_button in (
        (
            page.cpu1_ram_path_host,
            page.cpu1_ram_action_host,
            page.cpu1_ram_image_edit,
            page.cpu1_ram_browse_button,
        ),
        (
            page.cpu2_ram_path_host,
            page.cpu2_ram_action_host,
            page.cpu2_ram_image_edit,
            page.cpu2_ram_browse_button,
        ),
    ):
        assert abs(path_host.geometry().left() - action_host.geometry().left()) <= 1
        assert abs(path_host.width() - action_host.width()) <= 1
        assert image_edit.width() >= 300
        assert browse_button.width() >= 40

    page.close()
    app.processEvents()



def test_flash_target_and_execution_actions_align_with_field_editors() -> None:
    app = qt_app()
    page = AdvancedPage()
    page.resize(1440, 900)
    page.show()
    app.processEvents()

    page.tabs.setCurrentWidget(page.flash_tab)
    app.processEvents()
    flash_row = page.findChild(QWidget, "advancedFlashImageRow")
    target_field = page.flash_target_value.parentWidget()
    assert flash_row is not None
    assert target_field is not None
    target_label = target_field.findChild(QLabel)
    image_label = flash_row.findChild(QLabel)
    assert target_label is not None
    assert image_label is not None
    target_label_left = target_label.mapTo(page, target_label.rect().topLeft()).x()
    image_label_left = image_label.mapTo(page, image_label.rect().topLeft()).x()
    target_value_left = page.flash_target_value.mapTo(
        page, page.flash_target_value.rect().topLeft()
    ).x()
    image_edit_left = page.flash_image_edit.mapTo(
        page, page.flash_image_edit.rect().topLeft()
    ).x()
    assert abs(target_label_left - image_label_left) <= 2
    assert abs(target_value_left - image_edit_left) <= 2

    page.tabs.setCurrentWidget(page.execution_tab)
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
