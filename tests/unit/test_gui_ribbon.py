import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolButton

from bootloader_upgrade_tool.gui.app import configure_application
from bootloader_upgrade_tool.gui.layout_metrics import (
    RIBBON_CONTENT_ROW_HEIGHT,
    RIBBON_LARGE_BUTTON_HEIGHT,
    RIBBON_TRANSPORT_FIELD_HEIGHT,
    RIBBON_TRANSPORT_TAB_HEIGHT,
    RIBBON_TRANSPORT_TABS_HEIGHT,
)

from bootloader_upgrade_tool.gui.navigation import PageId
from bootloader_upgrade_tool.gui.widgets.ribbon import (
    DEFAULT_RIBBON_TAB,
    RIBBON_TAB_ORDER,
    OperateRibbon,
    RibbonTab,
    SessionRibbon,
    SettingsRibbon,
    ViewRibbon,
    create_default_ribbon,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_default_ribbon_has_frozen_hierarchy_order_and_default_tab() -> None:
    app = qt_app()
    ribbon = create_default_ribbon()

    assert ribbon.objectName() == "topRibbonShell"
    assert ribbon.title_row.objectName() == "titleTabRow"
    assert ribbon.tab_bar.objectName() == "ribbonTabBar"
    assert ribbon.content_row.objectName() == "ribbonContentRow"
    assert ribbon.page_stack.objectName() == "ribbonPageStack"
    assert ribbon.tab_order == RIBBON_TAB_ORDER
    assert ribbon.current_tab is DEFAULT_RIBBON_TAB is RibbonTab.OPERATE
    assert tuple(ribbon.tab_button(tab).text() for tab in RIBBON_TAB_ORDER) == (
        "Session",
        "Operate",
        "View",
        "Settings",
    )

    ribbon.set_current_tab(RibbonTab.VIEW)
    assert ribbon.current_tab is RibbonTab.VIEW
    assert ribbon.tab_button(RibbonTab.VIEW).isChecked()

    ribbon.close()
    app.processEvents()


def test_session_ribbon_preserves_content_but_disables_persistence_actions() -> None:
    app = qt_app()
    ribbon = SessionRibbon()

    for name in (
        "sessionNewButton",
        "sessionOpenButton",
        "sessionSaveButton",
        "sessionSaveAsButton",
        "sessionRecentButton",
    ):
        button = ribbon.findChild(QToolButton, name)
        assert button is not None
        assert not button.isEnabled()

    ribbon.set_session_state(
        current="Layout Preview",
        modified=True,
        path="D:/preview/session.json",
    )
    assert ribbon.current_value.text() == "Layout Preview"
    assert ribbon.modified_value.text() == "Yes"
    assert ribbon.path_value.text().endswith("session.json")

    ribbon.close()
    app.processEvents()


def test_operate_ribbon_is_static_and_tcp_stays_visible_disabled() -> None:
    app = qt_app()
    configure_application(app)
    ribbon = OperateRibbon()
    ribbon.resize(1000, RIBBON_CONTENT_ROW_HEIGHT)
    ribbon.show()
    app.processEvents()

    assert ribbon.transport_tabs.count() == 2
    assert ribbon.transport_tabs.height() == RIBBON_TRANSPORT_TABS_HEIGHT
    assert ribbon.transport_tabs.tabBar().height() == RIBBON_TRANSPORT_TAB_HEIGHT
    assert ribbon.sci_port_combo.height() == RIBBON_TRANSPORT_FIELD_HEIGHT
    assert ribbon.sci_baud_combo.height() == RIBBON_TRANSPORT_FIELD_HEIGHT
    sci_page = ribbon.transport_tabs.widget(0)
    assert ribbon.sci_port_combo.geometry().top() >= 0
    assert ribbon.sci_port_combo.geometry().bottom() < sci_page.height()
    assert ribbon.sci_baud_combo.geometry().bottom() < sci_page.height()
    assert ribbon.transport_tabs.tabText(0) == "SCI"
    assert ribbon.transport_tabs.tabText(1) == "TCP"
    assert ribbon.transport_tabs.isTabEnabled(0)
    assert not ribbon.transport_tabs.isTabEnabled(1)
    assert ribbon.sci_port_combo.count() == 1
    assert ribbon.sci_port_combo.currentData() is None
    assert not ribbon.connect_button.isEnabled()
    assert not ribbon.load_image_button.isEnabled()
    assert not ribbon.run_button.isEnabled()

    ribbon.set_operation_controls_enabled(True)
    assert ribbon.connect_button.isEnabled()
    assert ribbon.load_image_button.isEnabled()
    assert not ribbon.run_button.isEnabled()

    ribbon.set_connected(True)
    assert ribbon.connect_button.text() == "Disconnect"
    assert ribbon.run_button.isEnabled()

    ribbon.set_cpu_status("cpu1", "Connected", "connected")
    ribbon.set_cpu_status("CPU2", "Unavailable", "unavailable")
    assert ribbon.cpu1_status_dot.property("state") == "connected"
    assert ribbon.cpu1_status_text.text() == "Connected"
    assert ribbon.cpu2_status_dot.property("state") == "unavailable"

    ribbon.close()
    app.processEvents()


def test_view_and_settings_ribbons_emit_only_local_intents() -> None:
    app = qt_app()
    view = ViewRibbon()
    settings = SettingsRibbon()

    console_visibility: list[bool] = []
    auto_scroll: list[bool] = []
    clear_count: list[bool] = []
    pages: list[PageId] = []
    view.consoleVisibilityChanged.connect(console_visibility.append)
    view.consoleAutoScrollChanged.connect(auto_scroll.append)
    view.clearConsoleRequested.connect(lambda: clear_count.append(True))
    view.pageRequested.connect(pages.append)
    settings.pageRequested.connect(pages.append)

    view.console_toggle_button.click()
    view.console_auto_scroll_button.click()
    view.console_clear_button.click()
    view.open_logs_button.click()
    settings.open_settings_button.click()

    assert console_visibility == [False]
    assert auto_scroll == [False]
    assert clear_count == [True]
    assert pages == [PageId.LOGS, PageId.SETTINGS]
    assert not view.export_logs_button.isEnabled()
    assert not view.open_log_folder_button.isEnabled()
    assert not settings.save_global_button.isEnabled()
    assert not settings.reload_global_button.isEnabled()

    configure_application(app)
    view.resize(900, RIBBON_CONTENT_ROW_HEIGHT)
    view.show()
    app.processEvents()
    for button in (view.console_auto_scroll_button, view.open_logs_button):
        assert button.height() == RIBBON_LARGE_BUTTON_HEIGHT
        assert button.geometry().bottom() < view.height()

    view.close()
    settings.close()
    app.processEvents()
