from __future__ import annotations

from bootloader_upgrade_tool.gui.theme import theme_qss_text


def test_theme_keeps_input_indicators_and_file_picker_style() -> None:
    qss = theme_qss_text()

    required_selectors = (
        'QToolButton[filePickerButton="true"]',
        'QComboBox::drop-down',
        'QSpinBox::up-button',
        'QSpinBox::down-button',
        'QTabWidget#transportTabs QComboBox::drop-down',
    )
    for selector in required_selectors:
        assert selector in qss
