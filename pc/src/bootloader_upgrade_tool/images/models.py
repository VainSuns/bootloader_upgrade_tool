"""Prepared image models for PC-local operation setup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..firmware import FirmwareImage, build_firmware_image, run_hex2000
from ..image_workspace import ImageMaterializationWorkspace


@dataclass(frozen=True)
class ImageIdentity:
    entry_point: int
    image_size_words: int
    image_crc32: int
    app_end: int


@dataclass(frozen=True, slots=True)
class RamImageIdentity:
    entry_point: int
    total_words: int
    image_crc32: int

    def __post_init__(self) -> None:
        for name in ("entry_point", "total_words", "image_crc32"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class PreparedFlashImage:
    image: FirmwareImage
    identity: ImageIdentity
    sector_mask: int
    generated_sci8_txt: str | None = None


@dataclass(frozen=True)
class PreparedRamImage:
    image: FirmwareImage
    entry_point: int
    total_words: int
    image_crc32: int
    generated_sci8_txt: str | None = None


@dataclass(frozen=True)
class PreparedServiceImage:
    image: FirmwareImage
    descriptor_address: int
    api_table_address: int
    crc_patch_address: int
    total_words: int
    expected_crc32: int
    required_capabilities: int


def load_firmware_image(
    image_path: str | Path,
    *,
    hex2000: str | None = None,
    sci8_txt: str | Path | None = None,
    keep_sci8_txt: bool = False,
    work_dir: str | Path | None = None,
) -> tuple[FirmwareImage, str | None]:
    source = Path(image_path)
    if source.suffix.lower() == ".txt":
        return build_firmware_image(source, source), str(source)
    if sci8_txt:
        output = Path(sci8_txt)
        if not output.exists():
            run_hex2000(source, output, hex2000_path=hex2000)
        return build_firmware_image(source, output), str(output)
    if keep_sci8_txt:
        output = source.with_suffix(".sci8.txt")
        run_hex2000(source, output, hex2000_path=hex2000)
        return build_firmware_image(source, output), str(output)
    with ImageMaterializationWorkspace(source, work_dir) as materialization:
        run_hex2000(source, materialization.sci8_path, hex2000_path=hex2000)
        return build_firmware_image(source, materialization.sci8_path), None
