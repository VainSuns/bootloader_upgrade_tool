import os
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from bootloader_upgrade_tool.gui.app import (
    GuiLaunchOptions,
    configure_application,
    create_main_window,
)
from bootloader_upgrade_tool.gui.layout_metrics import (
    MAIN_AREA_MINIMUM_HEIGHT,
    WINDOW_MINIMUM_SIZE,
)
from bootloader_upgrade_tool.gui.navigation import PageId


VALIDATION_SIZES = (
    (1280, 760),
    (1440, 900),
    (1920, 1080),
)

# Qt creates these internal QTabBar scroll controls with fixed object names.
# They are framework-owned and may legitimately occur more than once.
_QT_INTERNAL_OBJECT_NAMES = frozenset(
    {
        "ScrollLeftButton",
        "ScrollRightButton",
    }
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("window_size", VALIDATION_SIZES)
def test_layout_preview_matrix_keeps_every_page_inside_the_workspace(
    window_size: tuple[int, int],
) -> None:
    app = qt_app()
    configure_application(app)
    window = create_main_window(GuiLaunchOptions(True, window_size))
    window.show()
    app.processEvents()

    assert (window.width(), window.height()) == window_size
    assert window.minimumWidth() == WINDOW_MINIMUM_SIZE[0]
    assert window.minimumHeight() == WINDOW_MINIMUM_SIZE[1]
    assert window.main_splitter.height() >= MAIN_AREA_MINIMUM_HEIGHT
    assert window.page_content_host.width() > 0
    assert window.page_content_host.height() > 0

    for page_id in PageId:
        window.navigate_to(page_id)
        app.processEvents()
        page = window.pages[page_id]
        assert window.page_stack.currentWidget() is page
        assert page.isVisible()
        assert page.width() <= window.page_content_host.width()
        assert page.height() <= window.page_content_host.height()

    assert not window.program_cpu2_page.interactions_enabled
    assert not window.memory_cpu2_page.interactions_enabled
    assert not window.advanced_page.erase_button.isEnabled()
    assert not window.advanced_page.program_only_button.isEnabled()
    assert not window.advanced_page.verify_only_button.isEnabled()
    assert not window.advanced_page.run_flash_app_button.isEnabled()
    assert not window.advanced_page.reset_target_button.isEnabled()

    window.close()
    app.processEvents()


def test_project_owned_object_names_are_unique() -> None:
    app = qt_app()
    configure_application(app)
    window = create_main_window(GuiLaunchOptions(True, (1440, 900)))
    window.show()
    app.processEvents()

    names = [
        widget.objectName()
        for widget in window.findChildren(QWidget)
        if widget.objectName()
        and not widget.objectName().startswith("qt_")
        and widget.objectName() not in _QT_INTERNAL_OBJECT_NAMES
    ]
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    assert duplicates == []

    window.close()
    app.processEvents()
