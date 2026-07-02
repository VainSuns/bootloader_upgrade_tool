import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_dsp_metadata_parser_and_scanner(tmp_path: Path) -> None:
    gcc = shutil.which("gcc")
    if gcc is None:
        pytest.skip("GCC is not available for the optional DSP metadata host check")

    test_c = tmp_path / "test_boot_metadata.c"
    test_c.write_text(
        r'''
#include <assert.h>
#include <stdint.h>
#include "boot_crc32.h"
#include "boot_metadata.h"

static void fill_words(uint16_t *words, uint32_t count, uint16_t value)
{
    uint32_t i;
    for (i = 0UL; i < count; i++)
    {
        words[i] = value;
    }
}

static void write_u32(uint16_t *words, uint16_t low_index, uint32_t value)
{
    words[low_index] = (uint16_t)(value & 0xFFFFUL);
    words[low_index + 1U] = (uint16_t)(value >> 16U);
}

static void finish_record(uint16_t *record)
{
    uint32_t crc = BootCrc32_CalcWords(record, BOOT_METADATA_RECORD_WORDS - 2UL);
    write_u32(record, 62U, crc);
}

static void make_record(uint16_t *record, uint16_t type, uint32_t sequence)
{
    fill_words(record, BOOT_METADATA_RECORD_WORDS, 0xFFFFU);
    record[0] = BOOT_METADATA_MAGIC0;
    record[1] = BOOT_METADATA_MAGIC1;
    record[2] = BOOT_METADATA_RECORD_VERSION;
    record[3] = (uint16_t)BOOT_METADATA_RECORD_WORDS;
    record[4] = type;
    write_u32(record, 5U, sequence);
    record[7] = BOOT_SLOT_A;
    record[8] = BOOT_SLOT_A;
    record[9] = 0U;
    write_u32(record, 10U, BOOT_METADATA_SLOT_A_APP_START);
    write_u32(record, 12U, BOOT_METADATA_SLOT_A_APP_END);
    write_u32(record, 14U, BOOT_METADATA_SLOT_A_APP_START);
    write_u32(record, 16U, 128UL);
    write_u32(record, 18U, 0x12345678UL);
    record[20] = 1U;
    record[21] = 2U;
    record[22] = 3U;
    write_u32(record, 23U, 4UL);
    record[25] = 0x377DU;
    record[26] = 1U;
    record[27] = BOOT_METADATA_BOOT_ATTEMPT_LIMIT;
    record[28] = 0U;
    finish_record(record);
}

static uint16_t *record_at(uint16_t *metadata, uint16_t index)
{
    return &metadata[(uint32_t)index * BOOT_METADATA_RECORD_WORDS];
}

static void scan(uint16_t *metadata, BootMetadataSummary *summary)
{
    BootMetadata_ScanRecords(metadata, BOOT_METADATA_SLOT_A_WORDS, summary);
}

int main(void)
{
    uint16_t metadata[BOOT_METADATA_SLOT_A_WORDS];
    uint16_t summary_payload[BOOT_METADATA_SUMMARY_WORDS];
    uint16_t built_record[BOOT_METADATA_RECORD_WORDS];
    BootMetadataSummary summary;
    BootMetadataRecord record;

    fill_words(metadata, BOOT_METADATA_SLOT_A_WORDS, 0xFFFFU);
    scan(metadata, &summary);
    assert(summary.state == BOOT_METADATA_SCAN_EMPTY);
    assert(summary.metadata_valid == 0U);
    assert(summary.erased_record_count == BOOT_METADATA_RECORD_COUNT);
    assert(summary.next_record_index == 0U);

    fill_words(metadata, BOOT_METADATA_SLOT_A_WORDS, 0xFFFFU);
    make_record(record_at(metadata, 0U), BOOT_METADATA_RECORD_IMAGE_VALID, 1UL);
    assert(BootMetadata_ValidateRecord(record_at(metadata, 0U), &record) == 1U);
    assert(record.record_type == BOOT_METADATA_RECORD_IMAGE_VALID);
    assert(record.sequence == 1UL);
    scan(metadata, &summary);
    assert(summary.state == BOOT_METADATA_SCAN_VALID);
    assert(summary.metadata_valid == 1U);
    assert(summary.has_image_valid == 1U);
    assert(summary.boot_attempt_count == 0U);
    assert(summary.entry_point == BOOT_METADATA_SLOT_A_APP_START);
    assert(summary.app_version_major == 1U);
    assert(summary.app_version_minor == 2U);
    assert(summary.app_version_patch == 3U);
    assert(summary.app_version_build == 4UL);
    assert(summary.target_device_id == 0x377DU);
    assert(summary.target_cpu_id == 1U);
    BootMetadataSummary_ToPayload(&summary, summary_payload);
    assert(summary_payload[0] == 1U);
    assert(summary_payload[5] == BOOT_METADATA_BOOT_ATTEMPT_LIMIT);
    assert(summary_payload[6] == 1U);
    assert(summary_payload[9] == 4U);
    assert(summary_payload[11] == (uint16_t)(BOOT_METADATA_SLOT_A_APP_START & 0xFFFFUL));
    assert(summary_payload[23] == 0x377DU);
    assert(summary_payload[24] == 1U);
    BootMetadata_BuildImageValidRecord(built_record, 7UL, BOOT_METADATA_SLOT_A_APP_START,
                                       16UL, 0x12345678UL, 1U, 2U, 3U, 4UL,
                                       BOOT_METADATA_SLOT_A_APP_START + 16UL,
                                       0x377DU, 1U);
    assert(built_record[4] == BOOT_METADATA_RECORD_IMAGE_VALID);
    assert(built_record[5] == 7U);
    assert(built_record[29] == 0xFFFFU);
    assert(BootMetadata_ValidateRecord(built_record, &record) == 1U);
    BootMetadata_BuildBootAttemptRecord(built_record, 8UL, &summary, 1U);
    assert(built_record[4] == BOOT_METADATA_RECORD_BOOT_ATTEMPT);
    assert(built_record[5] == 8U);
    assert(built_record[28] == 1U);
    assert(built_record[29] == 0xFFFFU);
    assert(BootMetadata_ValidateRecord(built_record, &record) == 1U);

    make_record(record_at(metadata, 1U), BOOT_METADATA_RECORD_BOOT_ATTEMPT, 2UL);
    scan(metadata, &summary);
    assert(summary.state == BOOT_METADATA_SCAN_VALID);
    assert(summary.boot_attempt_count == 1U);
    assert(summary.app_confirmed == 0U);
    assert(summary.latest_record_type == BOOT_METADATA_RECORD_BOOT_ATTEMPT);

    make_record(record_at(metadata, 2U), BOOT_METADATA_RECORD_APP_CONFIRMED, 3UL);
    scan(metadata, &summary);
    assert(summary.state == BOOT_METADATA_SCAN_VALID);
    assert(summary.boot_attempt_count == 1U);
    assert(summary.app_confirmed == 1U);
    assert(summary.app_confirmed_sequence == 3UL);

    make_record(record_at(metadata, 3U), BOOT_METADATA_RECORD_IMAGE_VALID, 4UL);
    record_at(metadata, 3U)[62] ^= 0x0001U;
    scan(metadata, &summary);
    assert(summary.state == BOOT_METADATA_SCAN_VALID);
    assert(summary.invalid_record_count == 1U);
    assert(summary.image_valid_sequence == 1UL);

    make_record(record_at(metadata, 3U), BOOT_METADATA_RECORD_IMAGE_VALID, 4UL);
    scan(metadata, &summary);
    assert(summary.state == BOOT_METADATA_SCAN_VALID);
    assert(summary.image_valid_sequence == 4UL);
    assert(summary.boot_attempt_count == 0U);
    assert(summary.app_confirmed == 0U);

    make_record(record_at(metadata, 4U), BOOT_METADATA_RECORD_BOOT_ATTEMPT, 4UL);
    scan(metadata, &summary);
    assert(summary.state == BOOT_METADATA_SCAN_DUPLICATE_SEQUENCE);
    assert(summary.metadata_valid == 0U);

    fill_words(metadata, BOOT_METADATA_SLOT_A_WORDS, 0xFFFFU);
    make_record(record_at(metadata, 0U), BOOT_METADATA_RECORD_IMAGE_VALID, 1UL);
    write_u32(record_at(metadata, 0U), 14U, BOOT_METADATA_SLOT_A_START);
    finish_record(record_at(metadata, 0U));
    scan(metadata, &summary);
    assert(summary.state == BOOT_METADATA_SCAN_INVALID);
    assert(summary.invalid_record_count == 1U);

    fill_words(metadata, BOOT_METADATA_SLOT_A_WORDS, 0xFFFFU);
    make_record(record_at(metadata, 0U), BOOT_METADATA_RECORD_IMAGE_VALID, 1UL);
    record_at(metadata, 0U)[7] = BOOT_SLOT_B;
    finish_record(record_at(metadata, 0U));
    scan(metadata, &summary);
    assert(summary.state == BOOT_METADATA_SCAN_INVALID);
    assert(summary.invalid_record_count == 1U);

    return 0;
}
''',
        encoding="utf-8",
    )

    executable = tmp_path / "test_boot_metadata.exe"
    subprocess.run(
        [
            gcc,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{ROOT / 'dsp' / 'bootloader_common' / 'include'}",
            str(ROOT / "dsp" / "bootloader_common" / "src" / "boot_crc32.c"),
            str(ROOT / "dsp" / "bootloader_common" / "src" / "boot_metadata.c"),
            str(test_c),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(executable)], check=True)
