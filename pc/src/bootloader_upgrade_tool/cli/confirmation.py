"""Interactive confirmation for CLI commands that mutate Flash."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
import sys
from typing import Any, TextIO


class ConfirmationDecision(str, Enum):
    APPROVED = "approved"
    DECLINED = "declined"
    CONFIRMATION_REQUIRED = "confirmation_required"


ConfirmationResult = ConfirmationDecision


def _display_value(key: str, value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        lowered = key.lower()
        if "mask" in lowered or "crc" in lowered or "point" in lowered:
            return f"0x{value:08X}"
    return str(value)


def request_confirmation(
    details: Mapping[str, Any],
    *,
    assume_yes: bool = False,
    stdin: TextIO | None = None,
    stderr: TextIO | None = None,
    is_tty: bool | None = None,
) -> ConfirmationDecision:
    """Request approval without ever writing prompts to stdout."""

    if assume_yes:
        return ConfirmationDecision.APPROVED

    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stderr if stderr is None else stderr
    tty = input_stream.isatty() if is_tty is None else is_tty
    for key, value in details.items():
        output_stream.write(f"{key}: {_display_value(str(key), value)}\n")
    if not tty:
        output_stream.write(
            "confirmation required: stdin is not a TTY; pass --yes to approve\n"
        )
        output_stream.flush()
        return ConfirmationDecision.CONFIRMATION_REQUIRED

    output_stream.write("Proceed? [y/N] ")
    output_stream.flush()
    answer = input_stream.readline().strip().lower()
    if answer in {"y", "yes"}:
        return ConfirmationDecision.APPROVED
    return ConfirmationDecision.DECLINED


__all__ = [
    "ConfirmationDecision",
    "ConfirmationResult",
    "request_confirmation",
]
