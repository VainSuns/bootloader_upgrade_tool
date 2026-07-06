"""Tiny TI linker map symbol parser for flash_service_lib patching."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True, slots=True)
class TiMapSymbols:
    descriptor_address: int
    crc_patch_address: int
    api_table_address: int


_SYMBOLS = {
    "descriptor_address": "g_boot_flash_service_descriptor",
    "crc_patch_address": "g_boot_flash_service_crc_patch",
    "api_table_address": "g_boot_flash_service_api",
}
_HEX = re.compile(r"(?:0x)?[0-9a-fA-F]{6,8}")


def _symbol_address(text: str, symbol: str) -> int:
    for line in text.splitlines():
        if symbol not in line:
            continue
        for match in _HEX.finditer(line):
            return int(match.group(0), 16)
    raise ValueError(f"missing TI map symbol: {symbol}")


def parse_flash_service_symbols_from_map(
    path: Path, *, descriptor_symbol: str | None = None
) -> TiMapSymbols:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return TiMapSymbols(
        descriptor_address=_symbol_address(
            text, descriptor_symbol or _SYMBOLS["descriptor_address"]
        ),
        crc_patch_address=_symbol_address(text, _SYMBOLS["crc_patch_address"]),
        api_table_address=_symbol_address(text, _SYMBOLS["api_table_address"]),
    )
