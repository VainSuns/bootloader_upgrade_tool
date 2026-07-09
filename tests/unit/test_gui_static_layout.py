import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QStackedWidget, QTableWidget, QTabWidget, QToolButton, QTreeWidget, QWidget

from bootloader_upgrade_tool.gui import BootloaderMainWindow, MainWindow
from bootloader_upgrade_tool.gui.styles import BOTTOM_DOCK_COLLAPSED_HEIGHT, BOTTOM_DOCK_EXPANDED_HEIGHT


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_bootloader_main_window_instantiates_and_closes() -> None:
    app = qt_app()
    window = BootloaderMainWindow()

    assert isinstance(window, MainWindow)

    window.close()
    app.processEvents()


def test_ribbon_tabs_and_default_operate_tab() -> None:
    app = qt_app()
    window = BootloaderMainWindow()

    assert list(window.ribbon._tab_buttons) == ["Session", "Operate", "View", "Settings"]
    assert window.ribbon._tab_buttons["Operate"].isChecked()
    assert window.ribbon.content_stack.currentIndex() == 1

    window.close()
    app.processEvents()


def test_navigation_structure_exists() -> None:
    app = qt_app()
    window = BootloaderMainWindow()
    tree = window.findChild(QTreeWidget, "navigationTree")

    assert tree is not None
    assert nav_text(tree) == [
        ("Program", ["CPU1", "CPU2"]),
        ("Settings", []),
        ("Memory", ["CPU1", "CPU2"]),
        ("Advanced", []),
        ("Logs", []),
    ]

    window.close()
    app.processEvents()


def test_default_page_is_cpu1_program() -> None:
    app = qt_app()
    window = BootloaderMainWindow()

    assert current_page_title(window) == "CPU1 Program"

    window.close()
    app.processEvents()


def test_ribbon_buttons_switch_to_logs_and_global_settings_pages() -> None:
    app = qt_app()
    window = BootloaderMainWindow()

    window.findChild(QToolButton, "openLogsButton").click()
    app.processEvents()
    assert current_page_title(window) == "Logs"

    window.findChild(QToolButton, "globalSettingsButton").click()
    app.processEvents()
    assert current_page_title(window) == "Global Settings"

    window.close()
    app.processEvents()


def test_advanced_tabs_and_ram_image_controls() -> None:
    app = qt_app()
    window = BootloaderMainWindow()
    window.show_page("advanced")
    tabs = window.findChild(QTabWidget, "advancedTabs")

    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "Diagnostics",
        "Flash",
        "Metadata",
        "Execution",
        "RAM Image",
    ]
    for name in [
        "ramCpu1ImagePathEdit",
        "ramCpu1ImageBrowseButton",
        "ramCpu2ImagePathEdit",
        "ramCpu2ImageBrowseButton",
    ]:
        assert window.findChild(QWidget, name) is not None
    for old_name in ["ramTargetCombo", "ramImageTargetCombo", "ramTargetSelector"]:
        assert window.findChild(QWidget, old_name) is None

    window.close()
    app.processEvents()


def test_memory_tables_default_shape_and_cells() -> None:
    app = qt_app()
    window = BootloaderMainWindow()

    for name in ["cpu1MemoryTable", "cpu2MemoryTable"]:
        table = window.findChild(QTableWidget, name)
        assert table is not None
        assert table.rowCount() == 100
        assert table.columnCount() == 17
        assert [table.horizontalHeaderItem(col).text() for col in range(17)] == ["Address"] + [f"+{i:X}" for i in range(16)]
        assert table.item(0, 1).text() == "????"
        assert table.item(99, 16).text() == "????"

    window.close()
    app.processEvents()


def test_bottom_console_collapses_and_expands() -> None:
    app = qt_app()
    window = BootloaderMainWindow()
    dock = window.bottom_dock

    assert dock.height() == BOTTOM_DOCK_EXPANDED_HEIGHT
    assert dock.title.text() == "Console"

    dock.toggle_collapsed()
    app.processEvents()
    assert dock.height() == BOTTOM_DOCK_COLLAPSED_HEIGHT
    assert dock.title.text() == "Console"

    dock.toggle_collapsed()
    app.processEvents()
    assert dock.height() == BOTTOM_DOCK_EXPANDED_HEIGHT
    assert dock.title.text() == "Console"

    window.close()
    app.processEvents()


def test_console_does_not_use_console_log_title() -> None:
    app = qt_app()
    window = BootloaderMainWindow()

    assert all(label.text() != "Console / Log" for label in window.findChildren(QLabel))

    window.close()
    app.processEvents()


def test_prefixed_summary_value_object_names_exist() -> None:
    app = qt_app()
    window = BootloaderMainWindow()

    for name in [
        "cpu1AppImageFileNameValue",
        "cpu1AppImageEntryPointValue",
        "cpu1AppImageImageSizeValue",
        "cpu1AppImageCrc32Value",
        "cpu1AppImageParseStatusValue",
        "cpu1StatusMetadataValidValue",
        "cpu1StatusImageValidValue",
        "cpu1StatusBootAttemptValue",
        "cpu1StatusAppConfirmedValue",
        "cpu1StatusConfirmedBootableValue",
        "cpu2AppImageFileNameValue",
        "cpu2StatusConfirmedBootableValue",
        "ramCpu1FileNameValue",
        "ramCpu1EntryPointValue",
        "ramCpu1LoadAddressValue",
        "ramCpu1ImageSizeValue",
        "ramCpu1Crc32Value",
        "ramCpu1ParseStatusValue",
        "ramCpu2ParseStatusValue",
    ]:
        assert window.findChild(QLabel, name) is not None

    window.close()
    app.processEvents()


def nav_text(tree: QTreeWidget) -> list[tuple[str, list[str]]]:
    items: list[tuple[str, list[str]]] = []
    for row in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(row)
        items.append((item.text(0), [item.child(index).text(0) for index in range(item.childCount())]))
    return items


def current_page_title(window: BootloaderMainWindow) -> str:
    stack = window.findChild(QStackedWidget, "pageContentStack")
    assert stack is not None
    title = stack.currentWidget().findChild(QLabel)
    assert title is not None
    return title.text()

def test_package_entrypoints_are_available() -> None:
    from bootloader_upgrade_tool.gui import BootloaderMainWindow, MainWindow, main, run
    from bootloader_upgrade_tool.gui.application import run as compatibility_run

    assert MainWindow is BootloaderMainWindow
    assert callable(main)
    assert callable(run)
    assert callable(compatibility_run)
