"""Generic stderr progress rendering for operation ProgressEvent values."""

from __future__ import annotations

import sys
import time
from typing import Callable, TextIO

from ..operations import ProgressEvent


class ProgressRenderer:
    """Render progress without inventing protocol-level progress semantics."""

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        is_tty: bool | None = None,
        clock: Callable[[], float] = time.monotonic,
        min_interval: float = 0.1,
    ) -> None:
        if min_interval < 0:
            raise ValueError("min_interval must be non-negative")
        self.stream = stream or sys.stderr
        self.is_tty = self.stream.isatty() if is_tty is None else is_tty
        self.clock = clock
        self.min_interval = min_interval
        self._last_emit_at: float | None = None
        self._last_stage: str | None = None
        self._workflow_stage: tuple[int, int, str] | None = None
        self._line_open = False

    def __call__(self, event: ProgressEvent) -> None:
        self.handle(event)

    def consume(self, event: ProgressEvent) -> None:
        self.handle(event)

    def handle(self, event: ProgressEvent) -> None:
        now = self.clock()
        completion = self._is_complete(event)
        important = (
            self._last_emit_at is None
            or event.stage != self._last_stage
            or completion
        )
        if not important and self._last_emit_at is not None:
            if now - self._last_emit_at < self.min_interval:
                return

        text = self._format_event(event)
        if self.is_tty:
            self.stream.write("\r" + text)
            self._line_open = True
            if completion:
                self.stream.write("\n")
                self._line_open = False
        else:
            self.stream.write(text + "\n")
        self.stream.flush()
        self._last_emit_at = now
        self._last_stage = event.stage

    def set_workflow_stage(self, index: int, total: int, name: str) -> None:
        if type(index) is not int or type(total) is not int or index < 1 or index > total:
            raise ValueError("workflow stage must satisfy 1 <= index <= total")
        if not name:
            raise ValueError("workflow stage name must be non-empty")
        self._workflow_stage = (index, total, name)
        self._last_emit_at = None
        self._last_stage = None
        label = f"[{index}/{total}] {name}"
        if self.is_tty:
            self.stream.write("\r" + label)
            self._line_open = True
        else:
            self.stream.write(label + "\n")
        self.stream.flush()

    def clear_workflow_stage(self) -> None:
        self._workflow_stage = None
        self._last_emit_at = None
        self._last_stage = None

    def finish(self) -> None:
        if self.is_tty and self._line_open:
            self.stream.write("\n")
            self.stream.flush()
            self._line_open = False

    close = finish

    @staticmethod
    def _is_complete(event: ProgressEvent) -> bool:
        if event.current_words is None or event.total_words is None:
            return False
        return event.current_words >= event.total_words

    def _format_event(self, event: ProgressEvent) -> str:
        text = f"{event.stage}: {event.message}"
        current = event.current_words
        total = event.total_words
        if current is not None and total is not None:
            if total > 0:
                percentage = min(100.0, max(0.0, current * 100.0 / total))
                text += f" ({current}/{total}, {percentage:.0f}%)"
            else:
                text += f" ({current}/{total})"
        elif current is not None:
            text += f" ({current} words)"
        if self._workflow_stage is not None:
            index, total, name = self._workflow_stage
            text = f"[{index}/{total} {name}] " + text
        return text


__all__ = ["ProgressRenderer"]
