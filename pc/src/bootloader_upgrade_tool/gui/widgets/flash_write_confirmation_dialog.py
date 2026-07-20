"""Read-only confirmation view for one frozen Flash write plan."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from ..flash_write_models import FlashWriteOperationType, FlashWritePlan


_NOT_APPLICABLE = "—"


class FlashWriteConfirmationDialog(QDialog):
    def __init__(self, plan: FlashWritePlan, parent) -> None:
        if type(plan) is not FlashWritePlan:
            raise TypeError("plan must be FlashWritePlan")
        super().__init__(parent)
        self.setObjectName("flashWriteConfirmationDialog")
        self.setWindowTitle("Confirm Flash Write")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        identity = plan.image_identity or plan.metadata_snapshot.raw_metadata

        self._add(form, "Operation", plan.operation_display_name, "flashWriteConfirmationOperationValue")
        self._add(form, "CPU", plan.cpu_id.value.upper(), "flashWriteConfirmationTargetValue")
        self._add(form, "Connection endpoint", plan.endpoint_label, "flashWriteConfirmationConnectionValue")
        self._add(form, "Connection generation", str(plan.connection_generation.value), "flashWriteConfirmationGenerationValue")
        self._add(form, "App image path", plan.image_source_path or _NOT_APPLICABLE, "flashWriteConfirmationImagePathValue")
        self._add(form, "Entry point", f"0x{identity.entry_point:08X}", "flashWriteConfirmationEntryPointValue")
        self._add(form, "Image size", f"{identity.image_size_words} words", "flashWriteConfirmationImageSizeValue")
        self._add(form, "Image CRC32", f"0x{identity.image_crc32:08X}", "flashWriteConfirmationCrc32Value")
        self._add(form, "Effective App sector mask", f"0x{plan.effective_sector_mask:08X}" if plan.effective_sector_mask is not None else _NOT_APPLICABLE, "flashWriteConfirmationSectorMaskValue")
        self._add(form, "Flash Service provider", plan.service_summary.provider_name, "flashWriteConfirmationServiceProviderValue")
        service_identity = f"{plan.service_summary.service_image_path} | {plan.service_summary.service_map_path}"
        self._add(form, "Flash Service image/map", service_identity, "flashWriteConfirmationServiceIdentityValue")
        self._add(form, "Flash Service descriptor", f"0x{plan.service_summary.descriptor_address:08X}", "flashWriteConfirmationServiceDescriptorValue")
        self._add(form, "Erase scope", plan.erase_scope.name if plan.erase_scope else _NOT_APPLICABLE, "flashWriteConfirmationEraseScopeValue")
        self._add(form, "Actual erase sector mask", f"0x{plan.erase_sector_mask:08X}" if plan.erase_sector_mask is not None else _NOT_APPLICABLE, "flashWriteConfirmationEraseMaskValue")
        self._add(form, "Metadata record", plan.metadata_record_name or _NOT_APPLICABLE, "flashWriteConfirmationMetadataRecordValue")
        self._add(form, "BOOT_ATTEMPT before", str(plan.boot_attempt_count_before) if plan.boot_attempt_count_before is not None else _NOT_APPLICABLE, "flashWriteConfirmationBootAttemptValue")
        self._add(form, "APP_CONFIRMED before", self._bool_text(plan.app_confirmed_before), "flashWriteConfirmationAppConfirmedValue")
        evidence = "Current VerifyEvidence is bound" if plan.operation_type is FlashWriteOperationType.WRITE_IMAGE_VALID else _NOT_APPLICABLE
        self._add(form, "Verify evidence", evidence, "flashWriteConfirmationVerifyEvidenceValue")

        warning = QLabel(
            "The operation may irreversibly modify target Flash.\n"
            "The displayed inputs are frozen for this confirmation.\n"
            "If the connection or inputs change, execution will be rejected.",
            self,
        )
        warning.setObjectName("flashWriteConfirmationWarning")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        buttons = QDialogButtonBox(self)
        confirm = buttons.addButton("Confirm", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        confirm.setObjectName("flashWriteConfirmButton")
        cancel.setObjectName("flashWriteCancelButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add(self, form: QFormLayout, title: str, value: str, object_name: str) -> None:
        label = QLabel(value, self)
        label.setObjectName(object_name)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(title, label)

    @staticmethod
    def _bool_text(value: bool | None) -> str:
        return _NOT_APPLICABLE if value is None else ("Yes" if value else "No")


__all__ = ["FlashWriteConfirmationDialog"]
