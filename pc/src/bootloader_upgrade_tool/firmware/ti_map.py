"""Tiny TI linker map symbol parser for flash_service_lib patching."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True, slots=True)
class TiMapSymbols:
    header_address: int
    publish_state_address: int
    runtime_state_address: int
    app_export_address: int
    immutable_start: int
    immutable_end_exclusive: int
    boot_init_address: int
    boot_handle_command_address: int
    confirm_current_image_address: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
                raise ValueError(f"{name} must fit uint32")
        if self.immutable_end_exclusive <= self.immutable_start:
            raise ValueError("immutable memory region must be non-empty")


_SYMBOLS = {
    "header_address": "g_boot_flash_service_header",
    "publish_state_address": "g_boot_flash_service_publish_state",
    "runtime_state_address": "g_service",
    "app_export_address": "g_boot_flash_service_app_export",
    "boot_init_address": "BootFlashService_BootInit",
    "boot_handle_command_address": "BootFlashService_BootHandleCommand",
    "confirm_current_image_address": "BootFlashService_ConfirmCurrentImage",
}
_HEX = re.compile(r"(?:0x)?[0-9a-fA-F]{6,8}")


def _symbol_address(text: str, symbol: str) -> int:
    for line in text.splitlines():
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", line) is None:
            continue
        for match in _HEX.finditer(line):
            return int(match.group(0), 16)
    raise ValueError(f"missing TI map symbol: {symbol}")


def _memory_region(text: str, name: str) -> tuple[int, int]:
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] != name:
            continue
        values = [int(match.group(0), 16) for match in _HEX.finditer(line)]
        if len(values) >= 2:
            return values[0], values[1]
    raise ValueError(f"missing TI map memory region: {name}")


def parse_flash_service_symbols_from_map(
    path: Path, *, header_symbol: str | None = None
) -> TiMapSymbols:
    text = path.read_text(encoding="utf-8", errors="ignore")
    immutable_start, immutable_length = _memory_region(text, "SERVICE_IMMUTABLE")
    if immutable_length == 0 or immutable_start + immutable_length > 0xFFFFFFFF:
        raise ValueError("invalid TI map memory region: SERVICE_IMMUTABLE")
    return TiMapSymbols(
        header_address=_symbol_address(text, header_symbol or _SYMBOLS["header_address"]),
        publish_state_address=_symbol_address(text, _SYMBOLS["publish_state_address"]),
        runtime_state_address=_symbol_address(text, _SYMBOLS["runtime_state_address"]),
        app_export_address=_symbol_address(text, _SYMBOLS["app_export_address"]),
        immutable_start=immutable_start,
        immutable_end_exclusive=immutable_start + immutable_length,
        boot_init_address=_symbol_address(text, _SYMBOLS["boot_init_address"]),
        boot_handle_command_address=_symbol_address(text, _SYMBOLS["boot_handle_command_address"]),
        confirm_current_image_address=_symbol_address(text, _SYMBOLS["confirm_current_image_address"]),
    )
