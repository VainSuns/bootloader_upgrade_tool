"""Locate hex2000, invoke it, and parse its ASCII SCI8 boot stream."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
from typing import Mapping, Sequence

from .models import FirmwareBlock, FirmwareImage


SCI8_KEY = 0x08AA
SCI8_RESERVED_WORDS = 8


class Hex2000Error(RuntimeError):
    """Base error for hex2000 discovery, execution, and output parsing."""


class Hex2000NotFoundError(Hex2000Error):
    pass


class Hex2000ConfigurationError(Hex2000Error):
    pass


class Sci8ParseError(Hex2000Error, ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Sci8BootTable:
    key: int
    reserved_words: tuple[int, ...]
    entry_point: int
    blocks: tuple[FirmwareBlock, ...]


def locate_hex2000(
    manual_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve hex2000 using an explicit path or ``C2000_CG_ROOT``."""

    env = os.environ if environ is None else environ
    if manual_path and str(manual_path).strip():
        try:
            manual = Path(manual_path).expanduser()
            candidate = manual / "hex2000.exe" if manual.is_dir() else manual
            if candidate.is_file():
                return candidate.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise Hex2000ConfigurationError(
                f"configured hex2000 path is invalid: {manual_path}"
            ) from exc
        raise Hex2000ConfigurationError(
            f"configured hex2000 path is invalid: {manual}"
        )

    candidates: list[Path] = []
    root_value = env.get("C2000_CG_ROOT")
    if root_value:
        root = Path(root_value).expanduser()
        candidates.extend((root / "bin" / "hex2000.exe", root / "hex2000.exe"))

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    searched = ", ".join(str(path) for path in candidates) or "no configured paths"
    raise Hex2000NotFoundError(
        f"hex2000.exe was not found ({searched}); configure a manual path or C2000_CG_ROOT"
    )


def run_hex2000(
    source_out_file: str | Path,
    generated_hex_file: str | Path,
    *,
    hex2000_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    timeout_seconds: float = 120.0,
) -> Path:
    source = Path(source_out_file)
    output = Path(generated_hex_file)
    if not source.is_file():
        raise FileNotFoundError(source)
    executable = locate_hex2000(hex2000_path, environ=environ)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        "-boot",
        "-a",
        "-sci8",
        "-o",
        str(output),
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hex2000Error(f"failed to execute hex2000: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic output"
        raise Hex2000Error(f"hex2000 failed with exit code {completed.returncode}: {detail}")
    if not output.is_file():
        raise Hex2000Error(f"hex2000 reported success but did not create {output}")
    return output


_TOKEN_RE = re.compile(r"(?<![0-9A-Za-z])(?:0[xX])?([0-9A-Fa-f]{2}|[0-9A-Fa-f]{4})(?![0-9A-Za-z])")


def _tokens(text: str) -> list[str]:
    cleaned = re.sub(r"/\*.*?\*/|//[^\r\n]*|#[^\r\n]*", " ", text, flags=re.DOTALL)
    return [match.group(1) for match in _TOKEN_RE.finditer(cleaned)]


def _parse_ascii_words(text: str) -> tuple[int, ...]:
    tokens = _tokens(text)
    if not tokens:
        raise Sci8ParseError("SCI8 output contains no hexadecimal data")
    widths = {len(token) for token in tokens}
    if widths == {4}:
        return tuple(int(token, 16) for token in tokens)
    if widths != {2}:
        raise Sci8ParseError("SCI8 output mixes byte and word tokens")
    byte_values = [int(token, 16) for token in tokens]
    if len(byte_values) % 2:
        raise Sci8ParseError("SCI8 byte stream has an odd byte count")
    return tuple(byte_values[index] | (byte_values[index + 1] << 8) for index in range(0, len(byte_values), 2))


def parse_sci8_text(text: str) -> Sci8BootTable:
    """Parse the standard C28x boot-table shape emitted for ASCII SCI8.

    Both two-digit little-endian byte tokens and four-digit word fixtures are
    accepted. The boot table is key, eight reserved words, uint32 entry point,
    then repeated ``size/address/data`` blocks terminated by a zero size.
    """

    words = _parse_ascii_words(text)
    fixed_words = 1 + SCI8_RESERVED_WORDS + 2
    if len(words) < fixed_words + 1:
        raise Sci8ParseError("SCI8 boot table is truncated")
    if words[0] != SCI8_KEY:
        raise Sci8ParseError(f"unexpected SCI8 key 0x{words[0]:04X}")
    entry_point = (words[9] << 16) | words[10]
    index = fixed_words
    blocks: list[FirmwareBlock] = []
    while True:
        if index >= len(words):
            raise Sci8ParseError("SCI8 boot table has no zero-length terminator")
        size = words[index]
        index += 1
        if size == 0:
            break
        if index + 2 + size > len(words):
            raise Sci8ParseError("SCI8 block extends beyond the available data")
        address = (words[index] << 16) | words[index + 1]
        index += 2
        blocks.append(FirmwareBlock(address, words[index : index + size]))
        index += size
    if index != len(words):
        raise Sci8ParseError("SCI8 boot table contains trailing data after terminator")
    if not blocks:
        raise Sci8ParseError("SCI8 boot table contains no data blocks")
    return Sci8BootTable(words[0], words[1:9], entry_point, tuple(blocks))


def parse_sci8_file(path: str | Path) -> Sci8BootTable:
    return parse_sci8_text(_decode_ascii(Path(path).read_bytes()))


def _decode_ascii(raw: bytes) -> str:
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise Sci8ParseError("SCI8 output is not ASCII") from exc


def build_firmware_image(
    source_out_file: str | Path,
    generated_hex_file: str | Path,
) -> FirmwareImage:
    generated = Path(generated_hex_file)
    raw = generated.read_bytes()
    table = parse_sci8_text(_decode_ascii(raw))
    return FirmwareImage(
        source_out_file=str(Path(source_out_file)),
        generated_hex_file=str(generated),
        entry_point=table.entry_point,
        blocks=table.blocks,
        file_checksum=hashlib.sha256(raw).hexdigest(),
        format_info={
            "format": "TI C2000 SCI8 ASCII boot table",
            "key": table.key,
            "reserved_words": table.reserved_words,
            "checksum": "sha256",
        },
    )
