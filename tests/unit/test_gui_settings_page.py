import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QLabel,
    QListWidget,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QWidget,
)

from bootloader_upgrade_tool.gui.layout_metrics import (
    SETTINGS_ACTION_BAR_HEIGHT,
    SETTINGS_CATEGORY_ITEM_HEIGHT,
    SETTINGS_CATEGORY_MAXIMUM_WIDTH,
    SETTINGS_CATEGORY_MINIMUM_WIDTH,
    SETTINGS_SCOPE_TAB_HEIGHT,
    SETTINGS_SCOPE_TAB_MINIMUM_WIDTH,
    SETTINGS_SPLITTER_HANDLE_WIDTH,
)
from bootloader_upgrade_tool.gui.pages import (
    CURRENT_CATEGORIES,
    GLOBAL_CATEGORIES,
    SettingsPage,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _list_text(widget: QListWidget) -> tuple[str, ...]:
    return tuple(widget.item(index).text() for index in range(widget.count()))


def test_settings_page_uses_frozen_scope_and_category_structure() -> None:
    app = qt_app()
    page = SettingsPage()

    assert page.objectName() == "settingsPage"
    assert (
        page.content_container.sizePolicy().horizontalPolicy()
        == QSizePolicy.Policy.Expanding
    )
    assert page.content_container.maximumWidth() >= 16_000_000
    assert page.findChild(QWidget, "settingsWidthHost") is None
    assert not page.scope_tabs.expanding()
    assert isinstance(page.scope_tabs, QTabBar)
    assert page.scope_tabs.objectName() == "settingsScopeTabs"
    assert page.scope_tabs.height() == SETTINGS_SCOPE_TAB_HEIGHT
    assert page.scope_tabs.minimumWidth() == 2 * SETTINGS_SCOPE_TAB_MINIMUM_WIDTH
    assert page.scope_tabs.count() == 2
    assert [page.scope_tabs.tabText(index) for index in range(2)] == [
        "Current Configuration",
        "Global Configuration",
    ]
    assert isinstance(page.scope_stack, QStackedWidget)
    assert page.scope_stack.count() == 2
    assert page.current_scope_key == "current"

    for scope in (page.current_scope, page.global_scope):
        assert isinstance(scope.splitter, QSplitter)
        assert scope.splitter.orientation() == Qt.Orientation.Horizontal
        assert not scope.splitter.childrenCollapsible()
        assert scope.splitter.handleWidth() == SETTINGS_SPLITTER_HANDLE_WIDTH
        assert scope.category_list.minimumWidth() == SETTINGS_CATEGORY_MINIMUM_WIDTH
        assert scope.category_list.maximumWidth() == SETTINGS_CATEGORY_MAXIMUM_WIDTH
        assert scope.action_bar.height() == SETTINGS_ACTION_BAR_HEIGHT
        for row in range(scope.category_list.count()):
            assert scope.category_list.item(row).sizeHint().height() == SETTINGS_CATEGORY_ITEM_HEIGHT

    assert _list_text(page.current_scope.category_list) == CURRENT_CATEGORIES
    assert _list_text(page.global_scope.category_list) == GLOBAL_CATEGORIES

    page.close()
    app.processEvents()


def test_cpu1_flash_service_controls_can_be_enabled_without_cpu2() -> None:
    page = SettingsPage()
    page.set_flash_service_controls_enabled(cpu1=True)
    assert page.cpu1_service_image.isEnabled()
    assert page.cpu1_service_map.isEnabled()
    assert page.cpu1_descriptor_symbol.isEnabled()
    assert not page.cpu2_service_image.isEnabled()
    assert not page.cpu2_service_map.isEnabled()
    assert not page.cpu2_descriptor_symbol.isEnabled()


def test_settings_scope_and_category_navigation_is_local_only() -> None:
    app = qt_app()
    page = SettingsPage()
    scopes: list[str] = []
    current_categories: list[str] = []
    global_categories: list[str] = []
    page.scopeChanged.connect(scopes.append)
    page.current_scope.categoryChanged.connect(current_categories.append)
    page.global_scope.categoryChanged.connect(global_categories.append)

    page.set_scope("global")
    assert page.current_scope_key == "global"
    assert page.scope_stack.currentWidget() is page.global_scope
    assert scopes == ["global"]

    page.global_scope.select_category("Flash Service")
    assert page.global_scope.category_stack.currentWidget() is page.global_scope.category_pages[
        "Flash Service"
    ]
    assert global_categories[-1] == "Flash Service"

    page.set_scope("current")
    page.current_scope.select_category("Program Options")
    assert page.current_scope.category_stack.currentWidget() is page.current_scope.category_pages[
        "Program Options"
    ]
    assert current_categories[-1] == "Program Options"

    with pytest.raises(ValueError, match="scope must be"):
        page.set_scope("workspace")
    with pytest.raises(KeyError, match="unknown current settings category"):
        page.current_scope.select_category("Erase Settings")

    page.close()
    app.processEvents()


def test_settings_fields_preserve_static_hardware_and_persistence_boundaries() -> None:
    app = qt_app()
    page = SettingsPage()

    assert page.current_transport_combo.currentText() == "SCI / RS232"
    assert page.current_baud_combo.currentText() == "9600"
    assert page.current_target_combo.currentText() == "Not identified"
    assert not page.current_confirm_app.isEnabled()

    assert page.global_scope.isEnabled()
    assert page.hex2000_path.path_edit.isEnabled()
    assert page.output_directory.path_edit.isEnabled()
    assert not page.keep_sci8_txt.isEnabled()
    assert not page.cpu1_service_image.path_edit.isEnabled()
    assert not page.cpu1_service_map.path_edit.isEnabled()
    assert not page.cpu1_descriptor_symbol.isEnabled()
    descriptor_value = page.findChild(QLabel, "globalCpu1DescriptorAddressValue")
    assert descriptor_value is not None
    assert "map/symbol" in descriptor_value.text()
    assert not page.cpu2_service_image.isEnabled()
    assert not page.cpu2_service_map.isEnabled()
    assert not page.cpu2_descriptor_symbol.isEnabled()

    tcp_banner = page.findChild(QWidget, "globalTcpDeferredBanner")
    assert tcp_banner is not None
    assert not tcp_banner.isEnabled()

    for name in (
        "resetCurrentButton",
        "applyCurrentButton",
        "reloadGlobalButton",
        "saveGlobalButton",
    ):
        button = page.findChild(QAbstractButton, name)
        assert button is not None
        assert not button.isEnabled()

    all_button_text = {button.text() for button in page.findChildren(QAbstractButton)}
    assert "SERVICE_ATTACH" not in all_button_text
    assert "Erase" not in all_button_text
    assert "Entire Flash" not in all_button_text

    page.close()
    app.processEvents()
