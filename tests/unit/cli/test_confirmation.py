from __future__ import annotations

import io

import pytest

from bootloader_upgrade_tool.cli.confirmation import (
    ConfirmationDecision,
    request_confirmation,
)


class Input(io.StringIO):
    def __init__(self, value: str, *, tty: bool) -> None:
        super().__init__(value)
        self.tty = tty
        self.reads = 0

    def isatty(self) -> bool:
        return self.tty

    def readline(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.reads += 1
        return super().readline(*args, **kwargs)


@pytest.mark.parametrize("answer", ["y\n", "yes\n", "Y\n", "YES\n"])
def test_interactive_yes_answers_are_approved(answer: str) -> None:
    stdin = Input(answer, tty=True)
    stderr = io.StringIO()

    result = request_confirmation(
        {"command": "program", "App path": "app.out"},
        stdin=stdin,
        stderr=stderr,
    )

    assert result is ConfirmationDecision.APPROVED
    assert stdin.reads == 1
    assert "command: program" in stderr.getvalue()
    assert "App path: app.out" in stderr.getvalue()
    assert "Proceed? [y/N]" in stderr.getvalue()


@pytest.mark.parametrize("answer", ["\n", "n\n", "no\n", "maybe\n"])
def test_interactive_non_yes_answers_are_declined(answer: str) -> None:
    result = request_confirmation(
        {"command": "erase"},
        stdin=Input(answer, tty=True),
        stderr=io.StringIO(),
    )

    assert result is ConfirmationDecision.DECLINED


def test_assume_yes_approves_without_reading_stdin_or_writing_prompt() -> None:
    stdin = Input("no\n", tty=False)
    stderr = io.StringIO()

    result = request_confirmation(
        {"command": "erase"},
        assume_yes=True,
        stdin=stdin,
        stderr=stderr,
    )

    assert result is ConfirmationDecision.APPROVED
    assert stdin.reads == 0
    assert stderr.getvalue() == ""


def test_non_tty_without_yes_requires_confirmation() -> None:
    stdin = Input("y\n", tty=False)
    stderr = io.StringIO()

    result = request_confirmation(
        {"command": "erase"},
        stdin=stdin,
        stderr=stderr,
    )

    assert result is ConfirmationDecision.CONFIRMATION_REQUIRED
    assert stdin.reads == 0
    assert "stdin is not a TTY" in stderr.getvalue()
