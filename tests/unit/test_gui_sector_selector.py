import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from bootloader_upgrade_tool.gui.widgets.sector_selector import (
    FlashSectorOption,
    SectorMaskSelector,
    SectorSelectionDialog,
)


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def sector_options() -> tuple[FlashSectorOption, ...]:
    return (
        FlashSectorOption("A", 0x080000, 0x081FFF, 0, protected=True),
        FlashSectorOption("B", 0x082000, 0x083FFF, 1),
        FlashSectorOption("C", 0x084000, 0x085FFF, 2),
        FlashSectorOption("D", 0x086000, 0x087FFF, 3),
    )


def test_dialog_is_dynamic_and_protected_sector_cannot_be_selected() -> None:
    app = qt_app()
    dialog = SectorSelectionDialog(
        sector_options(),
        selected_sector_ids=("A", "B"),
    )

    assert tuple(dialog.checkboxes) == ("A", "B", "C", "D")
    assert not dialog.checkboxes["A"].isEnabled()
    assert not dialog.checkboxes["A"].isChecked()
    assert dialog.checkboxes["B"].isChecked()

    dialog.checkboxes["C"].setChecked(True)
    assert dialog.selected_sector_ids() == ("B", "C")
    assert dialog.selected_mask() == 0x00000006

    dialog.close()
    app.processEvents()


def test_selector_uses_read_only_summary_and_computes_mask() -> None:
    app = qt_app()
    selector = SectorMaskSelector(
        sector_options(),
        selected_sector_ids=("B", "D"),
        object_name="testSectorSelector",
    )

    assert selector.summary_edit.isReadOnly()
    assert selector.selected_sector_ids() == ("B", "D")
    assert selector.selected_mask() == 0x0000000A
    assert selector.summary_edit.text() == "B, D  |  mask 0x0000000A"
    assert selector.edit_button.text() == "Edit…"
    assert selector.edit_button.property("variant") == "secondary"

    selector.set_selected_sector_ids(("A", "C"))
    assert selector.selected_sector_ids() == ("C",)
    assert selector.selected_mask() == 0x00000004

    selector.close()
    app.processEvents()


def test_empty_selector_is_deterministic_disabled_and_editor_is_noop() -> None:
    selector = SectorMaskSelector(())
    assert selector.sectors == ()
    assert selector.selected_sector_ids() == ()
    assert selector.selected_mask() == 0
    assert selector.summary_edit.text() == "Unavailable"
    assert not selector.edit_button.isEnabled()
    selector.open_editor()


def test_set_sectors_drops_unknown_and_protected_without_implicit_signal() -> None:
    selector = SectorMaskSelector(())
    emissions = []
    selector.selectionChanged.connect(lambda ids, mask: emissions.append((ids, mask)))
    selector.set_sectors(
        sector_options(), selected_sector_ids=("A", "B", "unknown"), emit=False
    )
    assert selector.selected_sector_ids() == ("B",)
    assert selector.selected_mask() == 2
    assert emissions == []
    selector.set_sectors(sector_options()[2:], selected_sector_ids=("C",), emit=True)
    assert emissions == [(('C',), 4)]


@pytest.mark.parametrize(
    "values",
    (
        (
            FlashSectorOption("B", 0, 1, 1),
            FlashSectorOption("B", 2, 3, 2),
        ),
        (
            FlashSectorOption("B", 0, 1, 1),
            FlashSectorOption("C", 2, 3, 1),
        ),
    ),
)
def test_set_sectors_rejects_duplicate_ids_or_bits(values) -> None:
    with pytest.raises(ValueError):
        SectorMaskSelector(values)
