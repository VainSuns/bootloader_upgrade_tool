from PySide6.QtWidgets import QApplication, QDialog, QWidget

from bootloader_upgrade_tool.gui.flash_write_confirmation import FlashWriteConfirmationCoordinator
from bootloader_upgrade_tool.gui.flash_write_models import FlashWriteOperationType
from test_gui_flash_write_models import plan


class Dialog(QDialog):
    def __init__(self, shown_plan, parent):
        super().__init__(parent)
        self.shown_plan = shown_plan
        self.opened = False

    def open(self):
        self.opened = True


def test_present_cancel_and_single_pending() -> None:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    dialogs = []
    factory = lambda shown, owner: dialogs.append(Dialog(shown, owner)) or dialogs[-1]
    coordinator = FlashWriteConfirmationCoordinator(main_window=parent, dialog_factory=factory)
    first_plan = plan(FlashWriteOperationType.PROGRAM_ONLY)
    request = object()
    calls = []
    assert coordinator.present(first_plan, request, lambda *args: calls.append(args))
    assert dialogs[0].opened and dialogs[0].shown_plan is first_plan
    assert not coordinator.present(plan(FlashWriteOperationType.PROGRAM_ONLY), object(), lambda: None)
    dialogs[0].reject()
    assert calls == [] and coordinator._pending is None


def test_confirm_passes_exact_objects_once_and_ignores_stale_signal() -> None:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    dialogs = []
    factory = lambda shown, owner: dialogs.append(Dialog(shown, owner)) or dialogs[-1]
    coordinator = FlashWriteConfirmationCoordinator(main_window=parent, dialog_factory=factory)
    shown_plan = plan(FlashWriteOperationType.PROGRAM_ONLY)
    request = object()
    calls = []
    coordinator.present(shown_plan, request, lambda *args: calls.append(args))
    dialogs[0].accepted.emit()
    dialogs[0].accepted.emit()
    assert calls == [(shown_plan, request)]
    coordinator.present(plan(FlashWriteOperationType.PROGRAM_ONLY), object(), lambda *args: calls.append(args))
    dialogs[0].accepted.emit()
    assert len(calls) == 1
    dialogs[1].reject()
