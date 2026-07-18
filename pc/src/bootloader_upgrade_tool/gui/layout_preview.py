"""Clearly labelled static data for Phase 11 multi-resolution layout review.

This module only mutates already-created View widgets.  It does not import or
call sessions, transports, protocol clients, image preparation, operations,
Flash services, metadata writers, or target code.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .main_window import BootloaderMainWindow

_LAYOUT_PREVIEW_TITLE_SUFFIX: Final = " — Layout Preview"

_CPU1_STATUS_PREVIEW: Final = {
    "metadata_valid": ("Valid [Preview]", "success"),
    "entry_point_valid": ("Valid [Preview]", "success"),
    "image_valid": ("Current image [Preview]", "success"),
    "flash_app_crc32": ("Matches [Preview]", "success"),
    "boot_attempt": ("Current image [Preview]", "success"),
    "loaded_image_matches": ("Yes [Preview]", "success"),
    "app_confirmed": ("Current image [Preview]", "success"),
    "confirmed_bootable": ("Yes [Preview]", "success"),
}

_CPU2_STATUS_PREVIEW: Final = {
    "metadata_valid": ("Unavailable", "unavailable"),
    "entry_point_valid": ("Unavailable", "unavailable"),
    "image_valid": ("Unavailable", "unavailable"),
    "flash_app_crc32": ("Unavailable", "unavailable"),
    "boot_attempt": ("Unavailable", "unavailable"),
    "loaded_image_matches": ("Unavailable", "unavailable"),
    "app_confirmed": ("Unavailable", "unavailable"),
    "confirmed_bootable": ("Unavailable", "unavailable"),
}

_MEMORY_CPU1_PREVIEW: Final = (
    (
        0x082000,
        (
            0x5A5A,
            0xA5A5,
            0x1234,
            0x5678,
            0x0001,
            0x0002,
            0x0003,
            0x0004,
            0x1111,
            0x2222,
            0x3333,
            0x4444,
            0x5555,
            0x6666,
            0x7777,
            0x8888,
        ),
    ),
    (0x082010, (0xCAFE, 0xBABE, 0x0F0F, 0xF0F0, 0x1357, 0x2468)),
)

_LOG_PREVIEW: Final = (
    {
        "time": "08:00:00.000",
        "level": "Info",
        "source": "GUI",
        "operation": "Layout Preview",
        "stage": "Startup",
        "message": "[Preview] Static layout review started; no transport was opened.",
    },
    {
        "time": "08:00:00.125",
        "level": "Protocol",
        "source": "Protocol",
        "operation": "Autobaud",
        "stage": "Not executed",
        "message": "[Preview] ASCII A / echo A is shown as contract text only.",
    },
    {
        "time": "08:00:00.250",
        "level": "Success",
        "source": "Layout",
        "operation": "Resolution Matrix",
        "stage": "Static",
        "message": "[Preview] Review 1280x760, 1440x900, and 1920x1080 manually.",
    },
    {
        "time": "08:00:00.375",
        "level": "Warning",
        "source": "CPU2",
        "operation": "Runtime",
        "stage": "Deferred",
        "message": "[Preview] CPU2 controls remain visible but runtime integration is disabled.",
    },
)


def apply_layout_preview(window: BootloaderMainWindow) -> None:
    """Populate one main window with static, explicitly-labelled preview data.

    The function is idempotent so repeated setup by tests or manual tooling does
    not duplicate Console records.
    """

    if window.property("layoutPreviewMode") is True:
        return
    window.setProperty("layoutPreviewMode", True)

    if not window.windowTitle().endswith(_LAYOUT_PREVIEW_TITLE_SUFFIX):
        window.setWindowTitle(window.windowTitle() + _LAYOUT_PREVIEW_TITLE_SUFFIX)

    _populate_program_pages(window)
    _populate_settings_page(window)
    _populate_advanced_page(window)
    _populate_memory_pages(window)
    _populate_logs_page(window)
    _populate_console(window)


def _populate_program_pages(window: BootloaderMainWindow) -> None:
    cpu1 = window.program_cpu1_page
    cpu1.set_image_summary(
        path="[Preview] C:/layout-preview/cpu1_app.txt",
        file_name="cpu1_app.txt",
        entry_point="0x082000 [Preview]",
        image_size="192 KiB [Preview]",
        crc32="0x7A4C2D91 [Preview]",
        parse_status="Prepared [Preview]",
        parse_state="success",
    )
    for key, (text, state) in _CPU1_STATUS_PREVIEW.items():
        cpu1.set_status(key, text, state)
    cpu1.set_details_text(
        "[Layout Preview]\n"
        "No image file was opened and no target operation was executed.\n"
        "This sample exercises long path, CRC32, metadata, and confirmed-bootable layouts."
    )

    cpu2 = window.program_cpu2_page
    cpu2.set_image_summary(
        path="[Preview] CPU2 runtime integration deferred",
        file_name="—",
        entry_point="Unavailable",
        image_size="Unavailable",
        crc32="Unavailable",
        parse_status="Unavailable",
        parse_state="unavailable",
    )
    for key, (text, state) in _CPU2_STATUS_PREVIEW.items():
        cpu2.set_status(key, text, state)
    cpu2.set_details_text(
        "[Layout Preview]\nCPU2 is visible for layout review; all runtime controls remain disabled."
    )


def _populate_settings_page(window: BootloaderMainWindow) -> None:
    settings = window.settings_page
    settings.set_scope("current")
    settings.current_baud_combo.setCurrentText("115200")
    settings.current_port_edit.setText("[Preview] COM7 — no port opened")
    settings.current_tx_timeout.setValue(1000)
    settings.current_rx_timeout.setValue(1000)
    settings.current_autobaud_timeout.setValue(5000)
    settings.current_force_load.setChecked(False)
    settings.current_auto_run.setChecked(True)


def _populate_advanced_page(window: BootloaderMainWindow) -> None:
    from ..targets import CPU1_PROFILE
    from .widgets.sector_selector import FlashSectorOption

    advanced = window.advanced_page
    advanced.tabs.setCurrentIndex(0)
    advanced.cpu1_flash_image_edit.setText(
        "[Preview] C:/layout-preview/cpu1_flash_app.txt"
    )
    advanced.cpu2_flash_image_edit.setText(
        "[Preview] C:/layout-preview/cpu2_flash_app.txt"
    )
    advanced.set_cpu1_flash_image_summary(
        app_end="0x09A000 [Preview]",
        entry_point="0x082400 [Preview]",
        image_size="96 KiB [Preview]",
        crc32="0x7A4C2D91 [Preview]",
        parse_status="Ready [Preview]",
    )
    advanced.set_cpu2_flash_image_summary(
        app_end="Not prepared [Preview]",
        entry_point="Not prepared [Preview]",
        image_size="Not prepared [Preview]",
        crc32="Not prepared [Preview]",
        parse_status="Not parsed [Preview]",
    )
    flash = CPU1_PROFILE.memory_map.flash
    assert flash is not None
    advanced.custom_sector_selector.set_sectors(tuple(
        FlashSectorOption(
            sector.sector_id,
            sector.start,
            sector.end_exclusive - 1,
            sector.bit_index,
            protected=bool(
                (1 << sector.bit_index) & flash.forbidden_erase_mask
                or (1 << sector.bit_index) & ~flash.allowed_erase_mask
            ),
        )
        for sector in flash.sectors
    ))
    advanced.erase_scope_combo.setCurrentText("Custom Sector Mask")
    advanced.custom_sector_selector.set_selected_sector_ids(
        ("B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M"),
        emit=False,
    )
    advanced.cpu1_ram_image_edit.setText(
        "[Preview] C:/layout-preview/cpu1_ram_image.txt"
    )
    advanced.cpu2_ram_image_edit.setText(
        "[Preview] C:/layout-preview/cpu2_ram_image.txt"
    )
    advanced.set_cpu1_ram_image_summary(
        target="CPU1 / TMS320F28377D",
        entry_point="RAM CPU1 entry [Preview]",
        image_size="24 KiB [Preview]",
        crc32="0x19A4E2C7 [Preview]",
    )
    advanced.set_cpu2_ram_image_summary(
        target="CPU2 / TMS320F28377D",
        entry_point="Not prepared [Preview]",
        image_size="Not prepared [Preview]",
        crc32="Not prepared [Preview]",
    )
    advanced.execution_entry_point.setText("0x082400 [Preview]")
    advanced.result_output.setPlainText(
        "[Layout Preview]\n"
        "No diagnostic, Flash, metadata, execution, or RAM operation was executed.\n"
        "Sector A protection, current-image metadata binding, and disabled CPU2 controls "
        "remain visible for review."
    )


def _populate_memory_pages(window: BootloaderMainWindow) -> None:
    window.memory_cpu1_page.set_memory_rows(_MEMORY_CPU1_PREVIEW, preview=True)
    window.memory_cpu2_page.set_memory_rows(((0x000000, ()),), preview=True)


def _populate_logs_page(window: BootloaderMainWindow) -> None:
    window.logs_page.set_records(_LOG_PREVIEW, preview=True)


def _populate_console(window: BootloaderMainWindow) -> None:
    console = window.bottom_dock
    console.clear()
    console.set_console_state("Preview", "warning")
    start = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    for index, (level, source, message) in enumerate(
        (
            (
                "warning",
                "GUI",
                "LAYOUT PREVIEW MODE: all displayed values are static samples.",
            ),
            (
                "info",
                "GUI",
                "No COM scan, autobaud, session, transport, or target operation was started.",
            ),
            (
                "protocol",
                "Protocol",
                "[Preview] SCI word order remains low byte then high byte; no bytes were sent.",
            ),
            (
                "success",
                "Layout",
                "Static preview data populated for Program, Settings, Advanced, Memory, Logs, and Console.",
            ),
        )
    ):
        console.append_message(
            level,
            source,
            message,
            timestamp=start + timedelta(milliseconds=125 * index),
        )


__all__ = ["apply_layout_preview"]
