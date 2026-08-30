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


def test_non_tty_workflow_stage_prefix_keeps_only_atomic_percentage() -> None:
    stream = io.StringIO()
    renderer = ProgressRenderer(stream, is_tty=False, clock=lambda: 0.0, min_interval=1.0)

    renderer.set_workflow_stage(2, 6, "PROGRAM")
    renderer(event("PROGRAM_DATA", 256, 1024, "writing"))

    lines = stream.getvalue().splitlines()
    assert lines[0] == "[2/6] PROGRAM"
    assert "[2/6 PROGRAM]" in lines[1]
    assert "25%" in lines[1]
    assert "33%" not in lines[1]


def test_tty_workflow_stage_appears_without_ansi_and_clear_removes_prefix() -> None:
    stream = io.StringIO()
    renderer = ProgressRenderer(stream, is_tty=True, clock=lambda: 0.0)

    renderer.set_workflow_stage(6, 6, "RUN")
    renderer(event("RUN", None, None, "request"))
    renderer.clear_workflow_stage()
    renderer(event("OTHER", None, None, "ordinary"))
    renderer.finish()

    rendered = stream.getvalue()
    assert "[6/6 RUN]" in rendered
    assert "[6/6 RUN] OTHER" not in rendered
    assert "\x1b[" not in rendered
    assert rendered.endswith("\n")


def test_workflow_stage_switch_forces_first_event_past_throttle() -> None:
    stream = io.StringIO()
    clock = Clock()
    renderer = ProgressRenderer(stream, is_tty=False, clock=clock, min_interval=1.0)

    renderer.set_workflow_stage(1, 6, "ERASE")
    renderer(event("ERASE", 1, 10))
    clock.value = 0.01
    renderer.set_workflow_stage(2, 6, "PROGRAM")
    renderer(event("PROGRAM_DATA", 1, 10))

    lines = stream.getvalue().splitlines()
    assert lines[-1].startswith("[2/6 PROGRAM] PROGRAM_DATA:")
