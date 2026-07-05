#include "boot_metadata.h"

#include "boot_crc32.h"

#include <stddef.h>

static void BootMetadata_WriteU32(uint16_t *words, uint16_t low_index, uint32_t value)
{
    words[low_index] = (uint16_t)(value & 0xFFFFUL);
    words[low_index + 1U] = (uint16_t)(value >> 16U);
}

void BootMetadata_BuildImageValidRecord(uint16_t *record_words,
                                        uint32_t sequence,
                                        uint32_t entry_point,
                                        uint32_t image_size_words,
                                        uint32_t image_crc32,
                                        uint16_t app_version_major,
                                        uint16_t app_version_minor,
                                        uint16_t app_version_patch,
                                        uint32_t app_version_build,
                                        uint32_t app_end,
                                        uint16_t target_device_id,
                                        uint16_t target_cpu_id)
{
    uint32_t index;
    uint32_t record_crc32;

    if (record_words == NULL)
    {
        return;
    }

    for (index = 0UL; index < BOOT_METADATA_RECORD_WORDS; index++)
    {
        record_words[index] = 0xFFFFU;
    }

    record_words[0] = BOOT_METADATA_MAGIC0;
    record_words[1] = BOOT_METADATA_MAGIC1;
    record_words[2] = BOOT_METADATA_RECORD_VERSION;
    record_words[3] = (uint16_t)BOOT_METADATA_RECORD_WORDS;
    record_words[4] = BOOT_METADATA_RECORD_IMAGE_VALID;
    BootMetadata_WriteU32(record_words, 5U, sequence);
    record_words[7] = BOOT_SLOT_A;
    record_words[8] = BOOT_SLOT_A;
    record_words[9] = 0U;
    BootMetadata_WriteU32(record_words, 10U, BOOT_METADATA_SLOT_A_APP_START);
    BootMetadata_WriteU32(record_words, 12U, app_end);
    BootMetadata_WriteU32(record_words, 14U, entry_point);
    BootMetadata_WriteU32(record_words, 16U, image_size_words);
    BootMetadata_WriteU32(record_words, 18U, image_crc32);
    record_words[20] = app_version_major;
    record_words[21] = app_version_minor;
    record_words[22] = app_version_patch;
    BootMetadata_WriteU32(record_words, 23U, app_version_build);
    record_words[25] = target_device_id;
    record_words[26] = target_cpu_id;
    record_words[27] = BOOT_METADATA_BOOT_ATTEMPT_LIMIT;
    record_words[28] = 0U;
    record_crc32 = BootCrc32_CalcWords(record_words, BOOT_METADATA_RECORD_WORDS - 2UL);
    BootMetadata_WriteU32(record_words, 62U, record_crc32);
}

void BootMetadata_BuildBootAttemptRecord(uint16_t *record_words,
                                         uint32_t sequence,
                                         const BootMetadataSummary *summary,
                                         uint16_t boot_attempt_count)
{
    uint32_t index;
    uint32_t record_crc32;

    if ((record_words == NULL) || (summary == NULL))
    {
        return;
    }

    for (index = 0UL; index < BOOT_METADATA_RECORD_WORDS; index++)
    {
        record_words[index] = 0xFFFFU;
    }

    record_words[0] = BOOT_METADATA_MAGIC0;
    record_words[1] = BOOT_METADATA_MAGIC1;
    record_words[2] = BOOT_METADATA_RECORD_VERSION;
    record_words[3] = (uint16_t)BOOT_METADATA_RECORD_WORDS;
    record_words[4] = BOOT_METADATA_RECORD_BOOT_ATTEMPT;
    BootMetadata_WriteU32(record_words, 5U, sequence);
    record_words[7] = BOOT_SLOT_A;
    record_words[8] = BOOT_SLOT_A;
    record_words[9] = 0U;
    BootMetadata_WriteU32(record_words, 10U, summary->app_start);
    BootMetadata_WriteU32(record_words, 12U, summary->app_end);
    BootMetadata_WriteU32(record_words, 14U, summary->entry_point);
    BootMetadata_WriteU32(record_words, 16U, summary->image_size_words);
    BootMetadata_WriteU32(record_words, 18U, summary->image_crc32);
    record_words[20] = summary->app_version_major;
    record_words[21] = summary->app_version_minor;
    record_words[22] = summary->app_version_patch;
    BootMetadata_WriteU32(record_words, 23U, summary->app_version_build);
    record_words[25] = summary->target_device_id;
    record_words[26] = summary->target_cpu_id;
    record_words[27] = summary->boot_attempt_limit;
    record_words[28] = boot_attempt_count;
    record_crc32 = BootCrc32_CalcWords(record_words, BOOT_METADATA_RECORD_WORDS - 2UL);
    BootMetadata_WriteU32(record_words, 62U, record_crc32);
}
