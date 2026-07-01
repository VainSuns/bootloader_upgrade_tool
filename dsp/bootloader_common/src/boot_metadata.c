#include "boot_metadata.h"

#include "boot_crc32.h"

#include <stddef.h>

static uint32_t BootMetadata_ReadU32(uint16_t low_word, uint16_t high_word)
{
    return ((uint32_t)low_word) | (((uint32_t)high_word) << 16U);
}

static uint16_t BootMetadata_IsRecordTypeValid(uint16_t record_type)
{
    return ((record_type == BOOT_METADATA_RECORD_IMAGE_VALID) ||
            (record_type == BOOT_METADATA_RECORD_BOOT_ATTEMPT) ||
            (record_type == BOOT_METADATA_RECORD_APP_CONFIRMED))
               ? 1U
               : 0U;
}

static uint16_t BootMetadata_AreAppFieldsValid(const BootMetadataRecord *record)
{
    if (record == NULL)
    {
        return 0U;
    }

    if (record->app_start != BOOT_METADATA_SLOT_A_APP_START)
    {
        return 0U;
    }

    if ((record->app_start >= record->app_end) ||
        (record->app_end > BOOT_METADATA_SLOT_A_APP_END))
    {
        return 0U;
    }

    if ((record->entry_point < BOOT_METADATA_SLOT_A_APP_START) ||
        (record->entry_point >= BOOT_METADATA_SLOT_A_APP_END) ||
        ((record->entry_point % 8UL) != 0UL))
    {
        return 0U;
    }

    if ((record->boot_attempt_limit == 0U) ||
        (record->boot_attempt_limit > BOOT_METADATA_BOOT_ATTEMPT_LIMIT))
    {
        return 0U;
    }

    return 1U;
}

void BootMetadata_InitSummary(BootMetadataSummary *summary)
{
    if (summary == NULL)
    {
        return;
    }

    summary->state = BOOT_METADATA_SCAN_EMPTY;
    summary->metadata_valid = 0U;
    summary->active_slot = BOOT_SLOT_AUTO;
    summary->has_image_valid = 0U;
    summary->app_confirmed = 0U;
    summary->latest_record_type = 0U;
    summary->valid_record_count = 0U;
    summary->invalid_record_count = 0U;
    summary->erased_record_count = 0U;
    summary->free_record_count = 0U;
    summary->next_record_index = BOOT_METADATA_INVALID_INDEX;
    summary->latest_sequence = 0UL;
    summary->image_valid_sequence = 0UL;
    summary->app_confirmed_sequence = 0UL;
    summary->app_start = 0UL;
    summary->app_end = 0UL;
    summary->entry_point = 0UL;
    summary->image_size_words = 0UL;
    summary->image_crc32 = 0UL;
    summary->app_version_major = 0U;
    summary->app_version_minor = 0U;
    summary->app_version_patch = 0U;
    summary->app_version_build = 0UL;
    summary->target_device_id = 0U;
    summary->target_cpu_id = 0U;
    summary->boot_attempt_limit = BOOT_METADATA_BOOT_ATTEMPT_LIMIT;
    summary->boot_attempt_count = 0U;
}

uint16_t BootMetadata_IsErasedRecord(const uint16_t *record_words)
{
    uint32_t index;

    if (record_words == NULL)
    {
        return 0U;
    }

    for (index = 0UL; index < BOOT_METADATA_RECORD_WORDS; index++)
    {
        if (record_words[index] != 0xFFFFU)
        {
            return 0U;
        }
    }

    return 1U;
}

uint16_t BootMetadata_ParseRecord(const uint16_t *record_words,
                                  BootMetadataRecord *record)
{
    if ((record_words == NULL) || (record == NULL))
    {
        return 0U;
    }

    record->record_type = record_words[4];
    record->sequence = BootMetadata_ReadU32(record_words[5], record_words[6]);
    record->slot_id = record_words[7];
    record->slot_role = record_words[8];
    record->flags = record_words[9];
    record->app_start = BootMetadata_ReadU32(record_words[10], record_words[11]);
    record->app_end = BootMetadata_ReadU32(record_words[12], record_words[13]);
    record->entry_point = BootMetadata_ReadU32(record_words[14], record_words[15]);
    record->image_size_words = BootMetadata_ReadU32(record_words[16], record_words[17]);
    record->image_crc32 = BootMetadata_ReadU32(record_words[18], record_words[19]);
    record->app_version_major = record_words[20];
    record->app_version_minor = record_words[21];
    record->app_version_patch = record_words[22];
    record->app_version_build = BootMetadata_ReadU32(record_words[23], record_words[24]);
    record->target_device_id = record_words[25];
    record->target_cpu_id = record_words[26];
    record->boot_attempt_limit = record_words[27];
    record->boot_attempt_count = record_words[28];
    record->record_crc32 = BootMetadata_ReadU32(record_words[62], record_words[63]);

    return 1U;
}

uint16_t BootMetadata_ValidateRecord(const uint16_t *record_words,
                                     BootMetadataRecord *record)
{
    BootMetadataRecord local_record;
    uint32_t expected_crc32;

    if (record_words == NULL)
    {
        return 0U;
    }

    if (BootMetadata_IsErasedRecord(record_words) != 0U)
    {
        return 0U;
    }

    if ((record_words[0] != BOOT_METADATA_MAGIC0) ||
        (record_words[1] != BOOT_METADATA_MAGIC1) ||
        (record_words[2] != BOOT_METADATA_RECORD_VERSION) ||
        (record_words[3] != (uint16_t)BOOT_METADATA_RECORD_WORDS) ||
        (BootMetadata_IsRecordTypeValid(record_words[4]) == 0U) ||
        (record_words[7] != BOOT_SLOT_A))
    {
        return 0U;
    }

    if (BootMetadata_ParseRecord(record_words, &local_record) == 0U)
    {
        return 0U;
    }

    expected_crc32 = BootCrc32_CalcWords(record_words, BOOT_METADATA_RECORD_WORDS - 2UL);
    if (local_record.record_crc32 != expected_crc32)
    {
        return 0U;
    }

    if (BootMetadata_AreAppFieldsValid(&local_record) == 0U)
    {
        return 0U;
    }

    if (record != NULL)
    {
        *record = local_record;
    }

    return 1U;
}

static void BootMetadata_CopyImageToSummary(BootMetadataSummary *summary,
                                            const BootMetadataRecord *record)
{
    summary->active_slot = record->slot_id;
    summary->has_image_valid = 1U;
    summary->image_valid_sequence = record->sequence;
    summary->app_start = record->app_start;
    summary->app_end = record->app_end;
    summary->entry_point = record->entry_point;
    summary->image_size_words = record->image_size_words;
    summary->image_crc32 = record->image_crc32;
    summary->app_version_major = record->app_version_major;
    summary->app_version_minor = record->app_version_minor;
    summary->app_version_patch = record->app_version_patch;
    summary->app_version_build = record->app_version_build;
    summary->target_device_id = record->target_device_id;
    summary->target_cpu_id = record->target_cpu_id;
    summary->boot_attempt_limit = record->boot_attempt_limit;
}

void BootMetadata_ScanRecords(const uint16_t *metadata_words,
                              uint32_t metadata_word_count,
                              BootMetadataSummary *summary)
{
    uint32_t record_count;
    uint32_t index;
    uint16_t duplicate_sequence = 0U;
    uint16_t has_latest = 0U;
    uint16_t has_image = 0U;
    uint16_t has_confirm = 0U;
    uint16_t sequence_count = 0U;
    uint32_t sequences[BOOT_METADATA_RECORD_COUNT];
    BootMetadataRecord record;
    BootMetadataRecord latest_record;
    BootMetadataRecord image_record;

    BootMetadata_InitSummary(summary);
    if ((summary == NULL) || (metadata_words == NULL))
    {
        return;
    }

    record_count = metadata_word_count / BOOT_METADATA_RECORD_WORDS;
    if (record_count > BOOT_METADATA_RECORD_COUNT)
    {
        record_count = BOOT_METADATA_RECORD_COUNT;
    }

    for (index = 0UL; index < record_count; index++)
    {
        const uint16_t *record_words = &metadata_words[index * BOOT_METADATA_RECORD_WORDS];
        uint16_t sequence_index;

        if (BootMetadata_IsErasedRecord(record_words) != 0U)
        {
            summary->erased_record_count++;
            summary->free_record_count++;
            if (summary->next_record_index == BOOT_METADATA_INVALID_INDEX)
            {
                summary->next_record_index = (uint16_t)index;
            }
            continue;
        }

        if (BootMetadata_ValidateRecord(record_words, &record) == 0U)
        {
            summary->invalid_record_count++;
            continue;
        }

        summary->valid_record_count++;
        for (sequence_index = 0U; sequence_index < sequence_count; sequence_index++)
        {
            if (sequences[sequence_index] == record.sequence)
            {
                duplicate_sequence = 1U;
            }
        }
        if (sequence_count < BOOT_METADATA_RECORD_COUNT)
        {
            sequences[sequence_count] = record.sequence;
            sequence_count++;
        }

        if ((has_latest == 0U) || (record.sequence > latest_record.sequence))
        {
            latest_record = record;
            has_latest = 1U;
        }

        if ((record.record_type == BOOT_METADATA_RECORD_IMAGE_VALID) &&
            ((has_image == 0U) || (record.sequence > image_record.sequence)))
        {
            image_record = record;
            has_image = 1U;
        }
    }

    if (has_latest != 0U)
    {
        summary->latest_sequence = latest_record.sequence;
        summary->latest_record_type = latest_record.record_type;
    }

    if (duplicate_sequence != 0U)
    {
        summary->state = BOOT_METADATA_SCAN_DUPLICATE_SEQUENCE;
        summary->metadata_valid = 0U;
        return;
    }

    if (has_image == 0U)
    {
        summary->state = ((summary->valid_record_count == 0U) &&
                          (summary->invalid_record_count == 0U))
                             ? BOOT_METADATA_SCAN_EMPTY
                             : BOOT_METADATA_SCAN_INVALID;
        return;
    }

    BootMetadata_CopyImageToSummary(summary, &image_record);

    for (index = 0UL; index < record_count; index++)
    {
        const uint16_t *record_words = &metadata_words[index * BOOT_METADATA_RECORD_WORDS];
        if (BootMetadata_ValidateRecord(record_words, &record) == 0U)
        {
            continue;
        }

        if (record.sequence <= image_record.sequence)
        {
            continue;
        }

        if (record.record_type == BOOT_METADATA_RECORD_BOOT_ATTEMPT)
        {
            summary->boot_attempt_count++;
        }
        else if ((record.record_type == BOOT_METADATA_RECORD_APP_CONFIRMED) &&
                 ((has_confirm == 0U) || (record.sequence > summary->app_confirmed_sequence)))
        {
            summary->app_confirmed = 1U;
            summary->app_confirmed_sequence = record.sequence;
            has_confirm = 1U;
        }
        else
        {
            /* Other valid record types after IMAGE_VALID do not affect summary. */
        }
    }

    summary->metadata_valid = 1U;
    summary->state = BOOT_METADATA_SCAN_VALID;
}
