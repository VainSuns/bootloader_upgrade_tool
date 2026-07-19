from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QWidget

from bootloader_upgrade_tool.gui.flash_write_models import FlashWriteOperationType
from bootloader_upgrade_tool.gui.widgets.flash_write_confirmation_dialog import FlashWriteConfirmationDialog
from test_gui_flash_write_models import plan


def test_dialog_is_window_modal_read_only_and_has_required_fields() -> None:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    dialog = FlashWriteConfirmationDialog(plan(FlashWriteOperationType.ERASE), parent)
    assert dialog.windowModality() is Qt.WindowModality.WindowModal
    names = {
        "flashWriteConfirmationOperationValue", "flashWriteConfirmationTargetValue",
        "flashWriteConfirmationConnectionValue", "flashWriteConfirmationGenerationValue",
        "flashWriteConfirmationImagePathValue", "flashWriteConfirmationEntryPointValue",
        "flashWriteConfirmationImageSizeValue", "flashWriteConfirmationCrc32Value",
        "flashWriteConfirmationSectorMaskValue", "flashWriteConfirmationMetadataRecordValue",
        "flashWriteConfirmationBootAttemptValue", "flashWriteConfirmationAppConfirmedValue",
        "flashWriteConfirmationWarning", "flashWriteConfirmButton", "flashWriteCancelButton",
    }
    assert all(dialog.findChild(QWidget, name) is not None for name in names)
    assert dialog.findChild(QLabel, "flashWriteConfirmationEraseMaskValue").text() == "0x00000002"
    assert dialog.findChild(QLabel, "flashWriteConfirmationMetadataRecordValue").text() == "—"
    assert not dialog.findChildren(QLineEdit)


def test_confirm_cancel_and_metadata_details() -> None:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    dialog = FlashWriteConfirmationDialog(plan(FlashWriteOperationType.WRITE_BOOT_ATTEMPT), parent)
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog.findChild(QPushButton, "flashWriteConfirmButton").click()
    assert accepted == [True]

    dialog = FlashWriteConfirmationDialog(plan(FlashWriteOperationType.WRITE_APP_CONFIRMED), parent)
    rejected = []
    dialog.rejected.connect(lambda: rejected.append(True))
    assert dialog.findChild(QLabel, "flashWriteConfirmationMetadataRecordValue").text() == "APP_CONFIRMED"
    assert dialog.findChild(QLabel, "flashWriteConfirmationBootAttemptValue").text() == "2"
    dialog.findChild(QPushButton, "flashWriteCancelButton").click()
    assert rejected == [True]
