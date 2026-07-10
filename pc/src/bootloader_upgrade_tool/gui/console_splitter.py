"""Local-only synchronization for the global Console splitter pane."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QSplitter

from .layout_metrics import (
    CONSOLE_COLLAPSED_HEIGHT,
    CONSOLE_DEFAULT_EXPANDED_HEIGHT,
    CONSOLE_MINIMUM_EXPANDED_HEIGHT,
    CONSOLE_START_COLLAPSED_WINDOW_HEIGHT,
    MAIN_AREA_MINIMUM_HEIGHT,
    RIBBON_TOTAL_HEIGHT,
)
from .widgets.console_widget import ConsoleWidget
from .widgets.ribbon import ViewRibbon

_QT_WIDGET_MAXIMUM: Final = 16_777_215


class ConsoleSplitterController(QObject):
    """Keep Console controls, visibility, and splitter height synchronized."""

    def __init__(
        self,
        splitter: QSplitter,
        console: ConsoleWidget,
        view_ribbon: ViewRibbon,
        *,
        window_height: Callable[[], int],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(splitter, QSplitter):
            raise TypeError("splitter must be a QSplitter")
        if not isinstance(console, ConsoleWidget):
            raise TypeError("console must be a ConsoleWidget")
        if not isinstance(view_ribbon, ViewRibbon):
            raise TypeError("view_ribbon must be a ViewRibbon")
        if not callable(window_height):
            raise TypeError("window_height must be callable")

        self._splitter = splitter
        self._console = console
        self._view_ribbon = view_ribbon
        self._window_height = window_height
        self._expanded_height = CONSOLE_DEFAULT_EXPANDED_HEIGHT

        view_ribbon.consoleVisibilityChanged.connect(self.set_expanded)
        view_ribbon.clearConsoleRequested.connect(console.clear)
        view_ribbon.consoleAutoScrollChanged.connect(
            console.auto_scroll_button.setChecked
        )
        console.expandedChanged.connect(self._on_console_expanded_changed)
        console.auto_scroll_button.toggled.connect(
            view_ribbon.set_console_auto_scroll
        )
        splitter.splitterMoved.connect(self._on_splitter_moved)

        self._configure_height(expanded=True)

    @property
    def expanded_height(self) -> int:
        return self._expanded_height

    def apply_initial_state(self) -> None:
        self.set_expanded(
            self._window_height() >= CONSOLE_START_COLLAPSED_WINDOW_HEIGHT
        )

    def set_expanded(self, expanded: bool) -> None:
        resolved = bool(expanded)
        if self._console.expanded == resolved:
            self._configure_height(resolved)
            self._resize_pane(resolved)
            self._view_ribbon.set_console_visible(resolved)
            return
        self._console.set_expanded(resolved)

    def _on_console_expanded_changed(self, expanded: bool) -> None:
        if not expanded:
            self._remember_height()
        self._configure_height(expanded)
        self._resize_pane(expanded)
        self._view_ribbon.set_console_visible(expanded)

    def _configure_height(self, expanded: bool) -> None:
        if expanded:
            self._console.setMinimumHeight(CONSOLE_MINIMUM_EXPANDED_HEIGHT)
            self._console.setMaximumHeight(_QT_WIDGET_MAXIMUM)
        else:
            self._console.setMinimumHeight(CONSOLE_COLLAPSED_HEIGHT)
            self._console.setMaximumHeight(CONSOLE_COLLAPSED_HEIGHT)

    def _resize_pane(self, expanded: bool) -> None:
        sizes = self._splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            total = max(
                MAIN_AREA_MINIMUM_HEIGHT + CONSOLE_MINIMUM_EXPANDED_HEIGHT,
                self._window_height() - RIBBON_TOTAL_HEIGHT,
            )

        if expanded:
            maximum_console = max(
                CONSOLE_MINIMUM_EXPANDED_HEIGHT,
                total - MAIN_AREA_MINIMUM_HEIGHT,
            )
            target_console = min(
                max(self._expanded_height, CONSOLE_MINIMUM_EXPANDED_HEIGHT),
                maximum_console,
            )
        else:
            target_console = CONSOLE_COLLAPSED_HEIGHT

        target_main = max(MAIN_AREA_MINIMUM_HEIGHT, total - target_console)
        self._splitter.setSizes([target_main, target_console])

    def _remember_height(self) -> None:
        sizes = self._splitter.sizes()
        if len(sizes) == 2 and sizes[1] >= CONSOLE_MINIMUM_EXPANDED_HEIGHT:
            self._expanded_height = sizes[1]

    def _on_splitter_moved(self, _position: int, _index: int) -> None:
        if self._console.expanded:
            self._remember_height()
