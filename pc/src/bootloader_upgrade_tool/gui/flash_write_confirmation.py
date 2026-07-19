"""Short-lived orchestration for independent Flash write confirmation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject

from .flash_write_models import FlashWritePlan
from .widgets.flash_write_confirmation_dialog import FlashWriteConfirmationDialog


@dataclass(slots=True)
class _PendingConfirmation:
    token: object
    plan: FlashWritePlan
    request: object
    callback: Callable[[FlashWritePlan, object], object]
    dialog: object


class FlashWriteConfirmationCoordinator(QObject):
    def __init__(self, *, main_window, dialog_factory=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._dialog_factory = dialog_factory or FlashWriteConfirmationDialog
        self._pending: _PendingConfirmation | None = None
        self.destroyed.connect(lambda _object=None: self._drop_pending(close=True))

    def present(self, plan: FlashWritePlan, request: object, on_confirm) -> bool:
        if type(plan) is not FlashWritePlan:
            raise TypeError("plan must be FlashWritePlan")
        if not callable(on_confirm):
            raise TypeError("on_confirm must be callable")
        if self._pending is not None:
            return False
        token = object()
        dialog = self._dialog_factory(plan, self._main_window)
        pending = _PendingConfirmation(token, plan, request, on_confirm, dialog)
        self._pending = pending
        dialog.accepted.connect(lambda token=token: self._accepted(token))
        dialog.rejected.connect(lambda token=token: self._rejected(token))
        dialog.open()
        return True

    def _accepted(self, token: object) -> None:
        pending = self._detach(token)
        if pending is None:
            return
        pending.dialog.deleteLater()
        pending.callback(pending.plan, pending.request)

    def _rejected(self, token: object) -> None:
        pending = self._detach(token)
        if pending is not None:
            pending.dialog.deleteLater()

    def _detach(self, token: object) -> _PendingConfirmation | None:
        pending = self._pending
        if pending is None or pending.token is not token:
            return None
        self._pending = None
        return pending

    def _drop_pending(self, *, close: bool) -> None:
        pending, self._pending = self._pending, None
        if pending is None:
            return
        try:
            pending.dialog.accepted.disconnect()
            pending.dialog.rejected.disconnect()
        except RuntimeError:
            pass
        if close:
            pending.dialog.reject()
        pending.dialog.deleteLater()


__all__ = ["FlashWriteConfirmationCoordinator"]
