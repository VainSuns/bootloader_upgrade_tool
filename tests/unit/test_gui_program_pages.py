import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
)

from bootloader_upgrade_tool.gui.app import configure_application
from bootloader_upgrade_tool.gui.layout_metrics import (
    PROGRAM_CONTENT_MAXIMUM_WIDTH,
    PROGRAM_IMAGE_CARD_MINIMUM_HEIGHT,
    PROGRAM_IMAGE_ROW_HEIGHT,
    PROGRAM_OPTIONS_CARD_MINIMUM_HEIGHT,
    PROGRAM_RESULT_CARD_MINIMUM_HEIGHT,
    PROGRAM_SPLITTER_HANDLE_WIDTH,
    PROGRAM_STATE_MAXIMUM_WIDTH,
    PROGRAM_STATE_MINIMUM_WIDTH,
    PROGRAM_STATUS_CARD_MINIMUM_HEIGHT,
    PROGRAM_STATUS_ROW_HEIGHT,
    PROGRAM_WORKFLOW_MAXIMUM_WIDTH,
    PROGRAM_WORKFLOW_MINIMUM_WIDTH,
)
from bootloader_upgrade_tool.gui.pages import (
    PROGRAM_STATUS_DEFINITIONS,
    ProgramTargetPage,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_cpu1_and_cpu2_share_frozen_program_page_structure() -> None:
    app = qt_app()
    cpu1 = ProgramTargetPage("cpu1")
    cpu2 = ProgramTargetPage("CPU2")

    assert type(cpu1) is type(cpu2) is ProgramTargetPage
    assert cpu1.objectName() == "programCpu1Page"
    assert cpu2.objectName() == "programCpu2Page"
    assert cpu1.header.title_label.text() == "CPU1 Program"
    assert cpu2.header.title_label.text() == "CPU2 Program"
    assert not cpu1.header.preview_badge.isHidden()
    assert not cpu2.header.preview_badge.isHidden()

    for page in (cpu1, cpu2):
        assert page.body_scroll_area.widgetResizable()
        assert (
            page.body_scroll_area.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert page.body_scroll_area.widget() is page.content_container
        assert page.content_container.maximumWidth() == PROGRAM_CONTENT_MAXIMUM_WIDTH
        assert page.horizontal_splitter.orientation() == Qt.Orientation.Horizontal
        assert not page.horizontal_splitter.childrenCollapsible()
        assert page.horizontal_splitter.handleWidth() == PROGRAM_SPLITTER_HANDLE_WIDTH
        assert page.horizontal_splitter.widget(0) is page.workflow_pane
        assert page.horizontal_splitter.widget(1) is page.state_pane
        assert page.workflow_pane.minimumWidth() == PROGRAM_WORKFLOW_MINIMUM_WIDTH
        assert page.workflow_pane.maximumWidth() == PROGRAM_WORKFLOW_MAXIMUM_WIDTH
        assert page.state_pane.minimumWidth() == PROGRAM_STATE_MINIMUM_WIDTH
        assert page.state_pane.maximumWidth() == PROGRAM_STATE_MAXIMUM_WIDTH

        assert page.app_image_card.minimumHeight() == PROGRAM_IMAGE_CARD_MINIMUM_HEIGHT
        assert page.program_options_card.minimumHeight() == PROGRAM_OPTIONS_CARD_MINIMUM_HEIGHT
        assert page.status_summary_card.minimumHeight() == PROGRAM_STATUS_CARD_MINIMUM_HEIGHT
        assert page.details_result_card.minimumHeight() == PROGRAM_RESULT_CARD_MINIMUM_HEIGHT
        assert not hasattr(page, "operation_progress_card")
        assert page.findChild(QAbstractButton, f"{page.object_prefix}CancelButton") is None

    cpu1.close()
    cpu2.close()
    app.processEvents()


def test_program_fields_options_statuses_and_result_contract() -> None:
    app = qt_app()
    page = ProgramTargetPage("cpu1")

    image_labels = [
        page.image_path_row.label_widget.text(),
        page.entry_point_row.label_widget.text(),
        page.image_size_row.label_widget.text(),
        page.crc32_row.label_widget.text(),
        page.parse_status_row.label_widget.text(),
    ]
    assert image_labels == [
        "App path",
        "Entry point",
        "Image size in words",
        "CRC32",
        "Parse status",
    ]
    assert not hasattr(page, "file_name_row")
    assert not hasattr(page, "target_row")
    for field in (
        page.entry_point_row,
        page.image_size_row,
        page.crc32_row,
    ):
        assert field.value_label.property("uiRole") == "valueLabel"
    assert page.details_result_card.parentWidget() is page.workflow_pane
    assert page.status_summary_card.parentWidget() is page.state_pane

    assert page.force_load_checkbox.text() == "Force Load"
    assert page.auto_run_checkbox.text() == "Auto Run after Load"
    assert page.confirm_app_checkbox.text() == "Confirm App"

    assert tuple(page.status_rows) == tuple(key for key, _ in PROGRAM_STATUS_DEFINITIONS)
    assert [row.label_widget.text() for row in page.status_rows.values()] == [
        label for _, label in PROGRAM_STATUS_DEFINITIONS
    ]
    assert isinstance(page.details_edit, QPlainTextEdit)
    assert page.details_edit.isReadOnly()
    assert page.details_edit.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap

    forbidden_actions = {
        "Erase",
        "Program",
        "Program Only",
        "Verify",
        "Verify Only",
        "SERVICE_ATTACH",
        "Load Image",
        "Run",
        "Cancel",
    }
    visible_actions = {button.text() for button in page.findChildren(QAbstractButton)}
    assert forbidden_actions.isdisjoint(visible_actions)

    page.close()
    app.processEvents()


def test_cpu1_local_signals_and_view_state_setters_do_not_touch_backend() -> None:
    app = qt_app()
    page = ProgramTargetPage("cpu1")
    browse_targets: list[str] = []
    prepare_targets: list[str] = []
    page.browseRequested.connect(browse_targets.append)
    page.prepareRequested.connect(prepare_targets.append)

    assert page.interactions_enabled
    assert page.image_path_row.browse_button.isEnabled()
    assert not page.prepare_image_button.isEnabled()

    page.image_path_row.browse_button.click()
    page.set_image_summary(
        path="D:/preview/app_cpu1.txt",
        file_name="app_cpu1.txt",
        entry_point="0x00090000",
        image_size="128 KiB",
        crc32="0x12345678",
        parse_status="Static Example",
        parse_state="warning",
    )
    assert page.prepare_image_button.isEnabled()
    page.prepare_image_button.click()

    assert page.entry_point_row.value_label.text() == "0x00090000"
    assert page.image_size_row.value_label.text() == "128 KiB"
    assert page.crc32_row.value_label.text() == "0x12345678"
    assert page.parse_status_row.badge.text() == "Static Example"
    assert page.parse_status_row.badge.property("state") == "warning"

    page.set_status("confirmed_bootable", "No", "warning")
    confirmed = page.status_rows["confirmed_bootable"].state_widget
    assert confirmed.text_label.text() == "No"
    assert confirmed.property("state") == "warning"
    with pytest.raises(KeyError, match="unknown Program status key"):
        page.set_status("not_a_status", "—", "unknown")

    page.set_details_text("Static details")
    page.append_details("Second line")
    assert page.details_edit.toPlainText().splitlines() == [
        "Static details",
        "Second line",
    ]
    page.clear_details_button.click()
    assert page.details_edit.toPlainText() == ""

    assert browse_targets == ["cpu1"]
    assert prepare_targets == ["cpu1"]

    page.close()
    app.processEvents()


def test_cpu2_program_controls_are_visible_but_disabled() -> None:
    app = qt_app()
    page = ProgramTargetPage("cpu2")

    assert not page.interactions_enabled
    for control in (
        page.image_path_row.path_edit,
        page.image_path_row.browse_button,
        page.prepare_image_button,
        page.force_load_checkbox,
        page.auto_run_checkbox,
        page.confirm_app_checkbox,
    ):
        assert not control.isEnabled()
    assert page.header.target_badge.property("state") == "unavailable"
    # Check the current deferred CPU2 contract, not obsolete Phase 11.1 wording.
    description = page.header.description_label.text().lower()
    assert "cpu2 program" in description and "deferred" in description

    page.close()
    app.processEvents()



def test_program_image_rows_do_not_overlap_after_theme_layout() -> None:
    app = qt_app()
    configure_application(app)
    page = ProgramTargetPage("cpu1")
    page.resize(1400, 650)
    page.show()
    app.processEvents()

    assert page.image_path_row.height() == PROGRAM_IMAGE_ROW_HEIGHT
    assert page.image_path_row.geometry().bottom() < page.image_summary_grid.geometry().top()

    entry_point = page.entry_point_row.geometry()
    image_size = page.image_size_row.geometry()
    crc32 = page.crc32_row.geometry()
    parse_status = page.parse_status_row.geometry()

    for row in (
        page.entry_point_row,
        page.image_size_row,
        page.crc32_row,
        page.parse_status_row,
    ):
        assert row.height() == PROGRAM_IMAGE_ROW_HEIGHT

    assert abs(entry_point.top() - image_size.top()) <= 2
    assert entry_point.right() < image_size.left()
    assert abs(crc32.top() - parse_status.top()) <= 2
    assert crc32.right() < parse_status.left()
    assert entry_point.bottom() < crc32.top()
    assert parse_status.bottom() < page.app_image_card.body.height()

    assert page.details_result_card.geometry().top() > page.program_options_card.geometry().bottom()
    assert page.status_summary_card.geometry().top() == page.app_image_card.geometry().top()
    assert (
        abs(
            page.status_summary_card.geometry().bottom()
            - page.details_result_card.geometry().bottom()
        )
        <= 2
    )
    for row in page.status_rows.values():
        assert row.height() == PROGRAM_STATUS_ROW_HEIGHT
    assert not any(
        label.text() == "Operation Progress"
        for label in page.findChildren(QLabel)
    )

    page.close()
    app.processEvents()

def test_program_page_rejects_unknown_target() -> None:
    qt_app()
    with pytest.raises(ValueError, match="target must be 'cpu1' or 'cpu2'"):
        ProgramTargetPage("cpu3")
