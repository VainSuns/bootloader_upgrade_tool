from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.gui.flash_sectors import (
    APP_FLASH_END_EXCLUSIVE,
    APP_FLASH_START,
    SLOT_A_APP_END_EXCLUSIVE,
    SLOT_A_APP_START,
    SLOT_A_METADATA_END,
    SLOT_A_METADATA_START,
    SLOT_A_METADATA_WORDS,
    calculate_sector_mask,
    validate_app_firmware_image,
)


def make_image(entry_point: int, address: int, words: tuple[int, ...] = (1, 2, 3)) -> FirmwareImage:
    return FirmwareImage(
        source_out_file="<test>",
        generated_hex_file="<test>",
        entry_point=entry_point,
        blocks=(FirmwareBlock(address, words),),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )


def test_slot_a_flash_layout_constants() -> None:
    assert SLOT_A_METADATA_START == 0x082000
    assert SLOT_A_METADATA_WORDS == 1024
    assert SLOT_A_METADATA_END == 0x082400
    assert SLOT_A_APP_START == 0x082400
    assert SLOT_A_APP_END_EXCLUSIVE == 0x0C0000
    assert SLOT_A_METADATA_END == SLOT_A_APP_START
    assert SLOT_A_METADATA_WORDS == SLOT_A_METADATA_END - SLOT_A_METADATA_START
    assert APP_FLASH_START == SLOT_A_APP_START
    assert APP_FLASH_END_EXCLUSIVE == SLOT_A_APP_END_EXCLUSIVE


def test_gui_sector_mask_rejects_sector_a() -> None:
    image = make_image(0x080000, 0x080000)

    try:
        calculate_sector_mask(image)
    except ValueError as exc:
        assert "Sector A" in str(exc)
    else:
        raise AssertionError("Sector A image should be rejected")


def test_app_validation_accepts_082400_and_keeps_flashb_mask() -> None:
    image = make_image(0x082400, 0x082400)

    validate_app_firmware_image(image)

    assert calculate_sector_mask(image) == 0x00000002


def test_app_validation_rejects_legacy_metadata_overlap() -> None:
    image = make_image(0x082000, 0x082000, tuple(range(1024)))

    try:
        validate_app_firmware_image(image)
    except ValueError as exc:
        message = str(exc)
        assert "Slot A metadata area 0x00082000-0x000823FF" in message
        assert "0x00082400" in message
    else:
        raise AssertionError("legacy metadata image should be rejected")


def test_app_validation_rejects_partial_metadata_overlap() -> None:
    image = make_image(0x082400, 0x0823F8, tuple(range(16)))

    try:
        validate_app_firmware_image(image)
    except ValueError as exc:
        assert "metadata" in str(exc)
    else:
        raise AssertionError("partial metadata overlap should be rejected")


def test_app_validation_rejects_bad_entry_and_block_end() -> None:
    for image in (
        make_image(0x082000, 0x082400),
        make_image(0x082400, 0x0BFFF8, tuple(range(16))),
    ):
        try:
            validate_app_firmware_image(image)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid App image should be rejected")
