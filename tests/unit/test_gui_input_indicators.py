import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from bootloader_upgrade_tool.gui.widgets.input_controls import (
    IndicatorComboBox,
    IndicatorSpinBox,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_combo_indicator_is_visible_and_preserves_text_width() -> None:
    app = qt_app()
    combo = IndicatorComboBox(indicator_width=24)
    combo.addItems(["9600", "115200"])
    combo.resize(112, 32)
    combo.show()
    app.processEvents()

    indicators = [
        child
        for child in combo.findChildren(QLabel)
        if child.accessibleName() == "Combo box direction indicator"
    ]
    assert len(indicators) == 1
    indicator = indicators[0]
    assert indicator.width() == 24
    assert indicator.x() == combo.width() - indicator.width()
    assert indicator.pixmap() is not None
    assert not indicator.pixmap().isNull()
    assert combo.minimumSizeHint().width() <= 112
    assert combo.minimumSizeHint().width() <= combo.width()


def test_spin_box_shows_separate_up_and_down_indicators() -> None:
    app = qt_app()
    spin = IndicatorSpinBox(indicator_width=22)
    spin.setRange(0, 600000)
    spin.setValue(5000)
    spin.resize(180, 34)
    spin.show()
    app.processEvents()

    up = next(
        child
        for child in spin.findChildren(QLabel)
        if child.accessibleName() == "Increase value"
    )
    down = next(
        child
        for child in spin.findChildren(QLabel)
        if child.accessibleName() == "Decrease value"
    )

    assert up.width() == 22
    assert down.width() == 22
    assert up.x() == spin.width() - 22
    assert down.x() == spin.width() - 22
    assert up.geometry().bottom() < down.geometry().bottom()
    assert up.pixmap() is not None and not up.pixmap().isNull()
    assert down.pixmap() is not None and not down.pixmap().isNull()
