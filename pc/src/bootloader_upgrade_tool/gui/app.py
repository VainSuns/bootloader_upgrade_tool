"""Application entry point and static layout-preview command-line options."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication, QStyle, QStyleFactory

from .layout_metrics import WINDOW_MINIMUM_SIZE
from .layout_preview import apply_layout_preview
from .main_window import BootloaderMainWindow
from .controller import GuiController
from .global_settings import load_global_settings
from .program_image_binding import ProgramImageBinding
from .runtime_backend import RuntimeBackend
from .runtime_binding import RuntimeViewBinding
from .serial_ports import SerialPortProvider, SystemSerialPortProvider
from .theme import apply_application_font, apply_palette_fallback, load_theme

_WINDOW_SIZE_PATTERN = re.compile(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$")


@dataclass(frozen=True, slots=True)
class GuiLaunchOptions:
    """GUI-only launch options parsed before Qt receives its own arguments."""

    layout_preview: bool = False
    window_size: tuple[int, int] | None = None


def parse_window_size(value: str) -> tuple[int, int]:
    """Parse ``WIDTHxHEIGHT`` while enforcing the frozen minimum window size."""

    match = _WINDOW_SIZE_PATTERN.fullmatch(value)
    if match is None:
        raise argparse.ArgumentTypeError(
            "window size must use WIDTHxHEIGHT, for example 1440x900"
        )

    width, height = (int(part) for part in match.groups())
    minimum_width, minimum_height = WINDOW_MINIMUM_SIZE
    if width < minimum_width or height < minimum_height:
        raise argparse.ArgumentTypeError(
            "window size must be at least "
            f"{minimum_width}x{minimum_height}; received {width}x{height}"
        )
    return width, height


def parse_gui_options(
    argv: Sequence[str],
) -> tuple[GuiLaunchOptions, list[str]]:
    """Parse project GUI options and preserve unknown arguments for Qt."""

    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--layout-preview",
        action="store_true",
        help=(
            "populate clearly labelled static preview data without opening a "
            "transport or executing a target operation"
        ),
    )
    parser.add_argument(
        "--window-size",
        metavar="WIDTHxHEIGHT",
        type=parse_window_size,
        help="override the initial logical-pixel window size",
    )
    namespace, qt_arguments = parser.parse_known_args(list(argv))
    return (
        GuiLaunchOptions(
            layout_preview=bool(namespace.layout_preview),
            window_size=namespace.window_size,
        ),
        qt_arguments,
    )


def create_fusion_style() -> QStyle:
    """Create the required Qt Fusion style before application QSS wraps it."""

    fusion_style = QStyleFactory.create("Fusion")
    if fusion_style is None:
        raise RuntimeError("Qt Fusion style is unavailable")
    return fusion_style


def configure_application(app: QApplication) -> None:
    """Apply the frozen Phase 11 application style pipeline."""

    app.setStyle(create_fusion_style())
    apply_application_font(app)
    apply_palette_fallback(app)
    load_theme(app)


def create_main_window(
    options: GuiLaunchOptions | None = None,
    *,
    runtime_backend: RuntimeBackend | None = None,
    serial_port_provider: SerialPortProvider | None = None,
) -> BootloaderMainWindow:
    """Create one main window with optional static preview configuration."""

    launch_options = options or GuiLaunchOptions()
    window = BootloaderMainWindow()
    if launch_options.window_size is not None:
        window.resize(*launch_options.window_size)
    if launch_options.layout_preview:
        apply_layout_preview(window)
    else:
        if runtime_backend is None:
            try:
                settings = load_global_settings()
            except (OSError, ValueError) as exc:
                settings = None
                settings_error = str(exc)
            else:
                settings_error = None
            backend = RuntimeBackend(
                hex2000_executable_path=settings.hex2000.executable_path if settings else None,
                global_settings_error=settings_error,
            )
        else:
            backend = runtime_backend
        controller = GuiController(backend, backend, parent=window)
        provider = serial_port_provider or SystemSerialPortProvider()
        binding = RuntimeViewBinding(
            window,
            controller,
            provider,
            main_window=window,
            parent=window,
        )
        window.runtime_backend = backend
        window.runtime_controller = controller
        window.serial_port_provider = provider
        window.attach_runtime_binding(binding)
        window.program_image_binding = ProgramImageBinding(
            window.program_cpu1_page,
            controller,
            backend,
            parent=window,
        )
    return window


def main(argv: Sequence[str] | None = None) -> int:
    """Run the desktop application."""

    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    options, qt_arguments = parse_gui_options(raw_arguments)

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0], *qt_arguments])
    configure_application(app)

    window = create_main_window(options)
    window.show()
    return app.exec()


run = main

__all__ = [
    "GuiLaunchOptions",
    "configure_application",
    "create_fusion_style",
    "create_main_window",
    "main",
    "parse_gui_options",
    "parse_window_size",
    "run",
]
