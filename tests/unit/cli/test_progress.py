from __future__ import annotations

import io

from bootloader_upgrade_tool.cli.progress import ProgressRenderer
from bootloader_upgrade_tool.operations import ProgressEvent


def event(stage: str, current: int | None, total: int | None, message: str = "working") -> ProgressEvent:
    return ProgressEvent("memory_read", "CPU1", stage, message, current, total)


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_tty_uses_dynamic_carriage_return_percentage_and_completion_newline() -> None:
    stream = io.StringIO()
    clock = Clock()
    renderer = ProgressRenderer(stream, is_tty=True, clock=clock, min_interval=1.0)

    renderer(event("MEMORY_READ", 1, 10))
    clock.value = 0.01
    renderer(event("MEMORY_READ", 2, 10))
    renderer(event("MEMORY_READ_END", 2, 10, "ending"))
    clock.value = 0.02
    renderer(event("MEMORY_READ_END", 10, 10, "done"))

    text = stream.getvalue()
    assert text.count("\r") == 3
    assert "(1/10, 10%)" in text
    assert "(2/10, 20%)" in text
    assert "(10/10, 100%)" in text
    assert text.endswith("\n")
    assert "\x1b[" not in text


def test_non_tty_emits_records_without_carriage_return_or_ansi_and_keeps_boundaries() -> None:
    stream = io.StringIO()
    clock = Clock()
    renderer = ProgressRenderer(stream, is_tty=False, clock=clock, min_interval=1.0)

    renderer(event("READ", 1, 10))
    clock.value = 0.01
    renderer(event("READ", 2, 10))
    renderer(event("VERIFY", 2, 10, "stage changed"))
    clock.value = 0.02
    renderer(event("VERIFY", 10, 10, "complete"))

    lines = stream.getvalue().splitlines()
    assert len(lines) == 3
    assert "1/10" in lines[0]
    assert "stage changed" in lines[1]
    assert "100%" in lines[2]
    assert "\r" not in stream.getvalue()
    assert "\x1b[" not in stream.getvalue()


def test_finish_ends_an_open_tty_line() -> None:
    stream = io.StringIO()
    renderer = ProgressRenderer(stream, is_tty=True, clock=lambda: 0.0)

    renderer(event("READ", None, None))
    renderer.finish()

    assert stream.getvalue().endswith("\n")
