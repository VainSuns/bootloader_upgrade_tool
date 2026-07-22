"""Application entry point and static layout-preview command-line options."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QFileDialog, QStyle, QStyleFactory

from ..app_resources import AppResourceProvider, load_development_resource_provider
from .advanced_read_binding import AdvancedReadOnlyBinding
from .advanced_flash_binding import AdvancedFlashBinding
from .advanced_flash_operation_binding import AdvancedFlashOperationBinding
from .advanced_metadata_binding import AdvancedMetadataOperationBinding
from .advanced_ram_binding import AdvancedRamBinding
from .cpu_program_status_binding import CpuProgramStatusBinding
from .layout_metrics import WINDOW_MINIMUM_SIZE
from .layout_preview import apply_layout_preview
from .memory_binding import MemoryRuntimeBinding
from .main_window import BootloaderMainWindow
from .navigation import PageId
from .controller import GuiController
from .global_settings_binding import GlobalSettingsBinding
from .persistence_stores import GlobalSettingsStore
from .session_application_service import SessionApplicationService
from .session_gui_binding import SessionGuiBinding
from .flash_service_binding import FlashServiceBinding
from .flash_write_confirmation import FlashWriteConfirmationCoordinator
from .program_image_binding import ProgramImageBinding
from .runtime_backend import RuntimeBackend
from .runtime_v2_models import RuntimeCpuId
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
    session_application_service: SessionApplicationService | None = None,
    global_settings_store: GlobalSettingsStore | None = None,
    session_dialog_provider=None,
    recent_sessions_dialog_factory=None,
    app_resource_provider: AppResourceProvider | None = None,
    development_resource_config_path: str | Path | None = None,
    sci8_workspace_root: str | Path | None = None,
) -> BootloaderMainWindow:
    """Create one main window with optional static preview configuration."""

    launch_options = options or GuiLaunchOptions()
    window = BootloaderMainWindow()
    if launch_options.window_size is not None:
        window.resize(*launch_options.window_size)
    if launch_options.layout_preview:
        apply_layout_preview(window)
    else:
        cache_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
        provider = (
            app_resource_provider
            if app_resource_provider is not None
            else load_development_resource_provider(development_resource_config_path)
        )
        workspace_root = (
            Path(sci8_workspace_root)
            if sci8_workspace_root is not None
            else Path(cache_dir) / "sci8"
        )
        backend = runtime_backend or RuntimeBackend(
            sci8_temp_dir=workspace_root,
            app_resource_provider=provider,
        )
        if runtime_backend is not None:
            backend.configure_app_resource_provider(provider)
        controller = GuiController(backend, backend, parent=window)
        serial_provider = serial_port_provider or SystemSerialPortProvider()
        binding = RuntimeViewBinding(
            window,
            controller,
            serial_provider,
            main_window=window,
            parent=window,
        )
        window.runtime_backend = backend
        window.runtime_controller = controller
        window.serial_port_provider = serial_provider
        window.app_resource_provider = provider
        window.sci8_workspace_root = workspace_root
        window.attach_runtime_binding(binding)
        window.memory_runtime_binding = MemoryRuntimeBinding(
            window.memory_cpu1_page,
            window.memory_cpu2_page,
            backend,
            parent=window,
        )
        window.cpu_program_status_binding = CpuProgramStatusBinding(
            window.program_cpu1_page,
            window.program_cpu2_page,
            controller,
            lambda: backend.active_target,
            backend=backend,
            parent=window,
        )
        window.advanced_read_binding = AdvancedReadOnlyBinding(
            window.advanced_page,
            controller,
            backend,
            manual_read_started=window.cpu_program_status_binding.consume_pending_auto_refresh,
            parent=window,
        )
        window.advanced_ram_binding = AdvancedRamBinding(
            window.advanced_page,
            controller,
            backend,
            parent=window,
        )
        window.program_image_bindings = MappingProxyType({
            RuntimeCpuId.CPU1: ProgramImageBinding(
                window.program_cpu1_page, controller, backend, parent=window
            ),
            RuntimeCpuId.CPU2: ProgramImageBinding(
                window.program_cpu2_page, controller, backend, parent=window
            ),
        })
        window.program_image_binding = window.program_image_bindings[RuntimeCpuId.CPU1]
        window.advanced_flash_binding = AdvancedFlashBinding(
            window.advanced_page,
            controller,
            backend,
            parent=window,
        )
        window.advanced_page.cpu1FlashBrowseRequested.connect(
            lambda: _navigate_to_program_image(
                window, PageId.PROGRAM_CPU1, window.program_cpu1_page
            )
        )
        window.advanced_page.cpu2FlashBrowseRequested.connect(
            lambda: _navigate_to_program_image(
                window, PageId.PROGRAM_CPU2, window.program_cpu2_page
            )
        )
        window.advanced_page.cpu1RamBrowseRequested.connect(
            lambda: _select_ram_image(window, window.advanced_ram_binding, "cpu1")
        )
        window.advanced_page.cpu2RamBrowseRequested.connect(
            lambda: _select_ram_image(window, window.advanced_ram_binding, "cpu2")
        )
        tools = window.settings_page
        window.flash_service_binding = FlashServiceBinding(
            tools,
            window.advanced_page,
            controller,
            backend,
            parent=window,
        )
        window.flash_write_confirmation_coordinator = (
            FlashWriteConfirmationCoordinator(main_window=window, parent=window)
        )
        window.advanced_flash_operation_binding = AdvancedFlashOperationBinding(
            window.advanced_page,
            controller,
            backend,
            window.flash_write_confirmation_coordinator,
            parent=window,
        )
        window.advanced_metadata_operation_binding = AdvancedMetadataOperationBinding(
            window.advanced_page,
            controller,
            backend,
            window.flash_write_confirmation_coordinator,
            parent=window,
        )
        tools.hex2000_path.browseRequested.connect(
            lambda: _select_hex2000_path(window, tools)
        )
        window.global_settings_binding = GlobalSettingsBinding(
            window,
            tools,
            window.settings_ribbon,
            controller,
            backend,
            global_settings_store or GlobalSettingsStore(),
            str(workspace_root),
            dialog_provider=session_dialog_provider,
            configuration_changed=lambda: _image_tool_configuration_changed(window),
            parent=window,
        )
        service = session_application_service or SessionApplicationService()
        window.session_application_service = service
        window.session_binding = SessionGuiBinding(
            window,
            window.session_ribbon,
            controller,
            backend,
            service,
            window.program_cpu1_page,
            window.program_cpu2_page,
            window.advanced_page,
            window.program_image_bindings,
            window.advanced_ram_binding,
            window.advanced_read_binding,
            dialog_provider=session_dialog_provider,
            recent_dialog_factory=recent_sessions_dialog_factory,
            parent=window,
        )
        window.attach_session_binding(window.session_binding)
    return window


def _select_hex2000_path(window, tools) -> None:
    path, _ = QFileDialog.getOpenFileName(window, "Select hex2000", "", "hex2000 (hex2000.exe)")
    if path:
        tools.hex2000_path.path_edit.setText(path)


def _navigate_to_program_image(window, page_id: PageId, page) -> None:
    window.navigate_to(page_id)
    page.image_path_row.path_edit.setFocus()


def _image_tool_configuration_changed(window) -> None:
    window.advanced_flash_binding.configuration_changed()
    window.flash_service_binding.tool_configuration_changed()
    window.advanced_flash_operation_binding.tool_configuration_changed()
    window.advanced_metadata_operation_binding.tool_configuration_changed()


def _select_ram_image(window, binding, target_key: str) -> None:
    path, _ = QFileDialog.getOpenFileName(
        window,
        f"Select {target_key.upper()} RAM Image",
        "",
        "RAM images (*.out *.txt)",
    )
    if path:
        binding.select_image(target_key, path)


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
