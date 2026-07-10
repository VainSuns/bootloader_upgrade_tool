import os
from enum import Enum

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from bootloader_upgrade_tool.gui.widgets import (
    LabeledFieldRow,
    NavigationItemSpec,
    NavigationPanel,
    NoticeBanner,
    PageHeader,
    PathFieldRow,
    ReadOnlyValueRow,
    ScopeBadge,
    SectionCard,
    StateIconLabel,
    StatusBadge,
    StatusDot,
    TargetPageHeader,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_card_and_page_header_contracts() -> None:
    app = qt_app()
    card = SectionCard("Status", semantic_icon="program.status.card")
    card.add_widget(QLabel("Static Example"))
    action = QPushButton("Refresh")
    card.header.add_action_widget(action)

    assert card.property("uiRole") == "card"
    assert card.header.property("uiRole") == "cardHeader"
    assert card.header.title_label.property("uiRole") == "cardTitle"
    assert card.body_layout.count() == 1
    assert card.header.actions_layout.count() == 1

    header = PageHeader("CPU1 Program", description="Layout Preview")
    header.add_action_widget(QPushButton("Action"))
    assert header.title_label.property("uiRole") == "pageTitle"
    assert header.description_label.property("uiRole") == "pageDescription"

    target = TargetPageHeader(
        "CPU2 Program",
        target_text="CPU2",
        target_state="unavailable",
        preview=True,
    )
    assert target.target_badge.text() == "CPU2"
    assert not target.preview_badge.isHidden()

    for widget in (card, header, target):
        widget.close()
    app.processEvents()


def test_status_and_banner_state_updates() -> None:
    app = qt_app()
    dot = StatusDot("busy")
    badge = StatusBadge("Busy", "busy")
    scope = ScopeBadge("Current", "current")
    state_label = StateIconLabel("Ready", "success")
    banner = NoticeBanner(
        "Static Example",
        "No hardware action is performed.",
        state="warning",
        semantic_icon="common.warning",
    )

    assert dot.property("uiRole") == "statusDot"
    assert badge.property("uiRole") == "statusBadge"
    assert scope.property("scope") == "current"
    assert state_label.state == "success"
    assert banner.property("state") == "warning"

    dot.set_state("error")
    badge.set_status("Failed", "error")
    scope.set_scope("Global", "global")
    state_label.set_state("warning", text="Review")
    banner.set_state("error")

    assert dot.property("state") == "error"
    assert badge.text() == "Failed"
    assert scope.property("scope") == "global"
    assert state_label.text_label.text() == "Review"
    assert banner.property("state") == "error"

    for widget in (dot, badge, scope, state_label, banner):
        widget.close()
    app.processEvents()


def test_form_rows_expose_only_local_widget_behavior() -> None:
    app = qt_app()
    editor = QLineEdit()
    row = LabeledFieldRow("Port", editor, helper_text="Layout Preview")
    path_row = PathFieldRow(
        "App image",
        edit_object_name="appImagePathEdit",
        button_object_name="appImageBrowseButton",
    )
    value_row = ReadOnlyValueRow(
        "CRC32",
        "0x12345678",
        value_object_name="crc32Value",
    )

    emitted: list[bool] = []
    path_row.browseRequested.connect(lambda: emitted.append(True))
    path_row.browse_button.click()

    assert row.editor is editor
    assert row.label_widget.property("uiRole") == "fieldLabel"
    assert row.helper_label.property("uiRole") == "helperText"
    assert path_row.path_edit.objectName() == "appImagePathEdit"
    assert path_row.browse_button.objectName() == "appImageBrowseButton"
    assert emitted == [True]
    assert value_row.value_label.textInteractionFlags()
    assert value_row.value_label.property("uiRole") == "valueLabel"

    for widget in (row, path_row, value_row):
        widget.close()
    app.processEvents()


class PageId(Enum):
    PROGRAM_CPU1 = "program.cpu1"
    PROGRAM_CPU2 = "program.cpu2"
    SETTINGS = "settings"


def test_navigation_panel_emits_stable_page_objects_only_for_leaves() -> None:
    app = qt_app()
    panel = NavigationPanel(
        (
            NavigationItemSpec(
                "Program",
                "navigation.program",
                children=(
                    NavigationItemSpec(
                        "CPU1",
                        "navigation.program.cpu1",
                        PageId.PROGRAM_CPU1,
                    ),
                    NavigationItemSpec(
                        "CPU2",
                        "navigation.program.cpu2",
                        PageId.PROGRAM_CPU2,
                    ),
                ),
            ),
            NavigationItemSpec(
                "Settings",
                "navigation.settings",
                PageId.SETTINGS,
            ),
        )
    )
    activated: list[PageId] = []
    panel.pageActivated.connect(activated.append)

    panel.select_page(PageId.PROGRAM_CPU1)
    assert panel.selected_page() is PageId.PROGRAM_CPU1
    assert activated == []

    panel.select_page(PageId.SETTINGS, emit=True)
    assert activated == [PageId.SETTINGS]
    assert panel.page_item(PageId.PROGRAM_CPU2).text(0) == "CPU2"

    panel.close()
    app.processEvents()
