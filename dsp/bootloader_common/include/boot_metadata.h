#ifndef BOOT_METADATA_H
#define BOOT_METADATA_H

#include <stdint.h>

#define BOOT_METADATA_SLOT_A_START          0x082000UL
#define BOOT_METADATA_SLOT_A_WORDS          1024UL
#define BOOT_METADATA_RECORD_WORDS          64UL
#define BOOT_METADATA_RECORD_COUNT          16UL
#define BOOT_METADATA_SUMMARY_WORDS         25U
#define BOOT_METADATA_SLOT_A_APP_START      0x082400UL
#define BOOT_METADATA_SLOT_A_APP_END        0x0C0000UL
#define BOOT_METADATA_BOOT_ATTEMPT_LIMIT    3U

#define BOOT_METADATA_MAGIC0                0x4D42U
#define BOOT_METADATA_MAGIC1                0x4453U
#define BOOT_METADATA_RECORD_VERSION        0x0001U

#define BOOT_METADATA_RECORD_IMAGE_VALID    0x0001U
#define BOOT_METADATA_RECORD_BOOT_ATTEMPT   0x0002U
#define BOOT_METADATA_RECORD_APP_CONFIRMED  0x0003U

#define BOOT_SLOT_AUTO                      0x0000U
#define BOOT_SLOT_A                         0x0001U
#define BOOT_SLOT_B                         0x0002U

#define BOOT_METADATA_INVALID_INDEX         0xFFFFU

typedef enum
{
    BOOT_METADATA_SCAN_EMPTY = 0,
    BOOT_METADATA_SCAN_VALID = 1,
    BOOT_METADATA_SCAN_INVALID = 2,
    BOOT_METADATA_SCAN_DUPLICATE_SEQUENCE = 3
} BootMetadataScanState;

typedef struct
{
    uint16_t record_type;
    uint32_t sequence;
    uint16_t slot_id;
    uint16_t slot_role;
    uint16_t flags;
    uint32_t app_start;
    uint32_t app_end;
    uint32_t entry_point;
    uint32_t image_size_words;
    uint32_t image_crc32;
    uint16_t app_version_major;
    uint16_t app_version_minor;
    uint16_t app_version_patch;
    uint32_t app_version_build;
    uint16_t target_device_id;
    uint16_t target_cpu_id;
    uint16_t boot_attempt_limit;
    uint16_t boot_attempt_count;
    uint32_t record_crc32;
} BootMetadataRecord;

typedef struct
{
    BootMetadataScanState state;
    uint16_t metadata_valid;
    uint16_t active_slot;
    uint16_t has_image_valid;
    uint16_t app_confirmed;
    uint16_t latest_record_type;
    uint16_t valid_record_count;
    uint16_t invalid_record_count;
    uint16_t erased_record_count;
    uint16_t free_record_count;
    uint16_t next_record_index;
    uint32_t latest_sequence;
    uint32_t image_valid_sequence;
    uint32_t app_confirmed_sequence;
    uint32_t app_start;
    uint32_t app_end;
    uint32_t entry_point;
    uint32_t image_size_words;
    uint32_t image_crc32;
    uint16_t app_version_major;
    uint16_t app_version_minor;
    uint16_t app_version_patch;
    uint32_t app_version_build;
    uint16_t target_device_id;
    uint16_t target_cpu_id;
    uint16_t boot_attempt_limit;
    uint16_t boot_attempt_count;
} BootMetadataSummary;

void BootMetadata_InitSummary(BootMetadataSummary *summary);
uint16_t BootMetadata_IsErasedRecord(const uint16_t *record_words);
uint16_t BootMetadata_ParseRecord(const uint16_t *record_words,
                                  BootMetadataRecord *record);
uint16_t BootMetadata_ValidateRecord(const uint16_t *record_words,
                                     BootMetadataRecord *record);
void BootMetadata_ScanRecords(const uint16_t *metadata_words,
                              uint32_t metadata_word_count,
                              BootMetadataSummary *summary);
void BootMetadata_ScanFlashRecords(uint32_t metadata_start,
                                   BootMetadataSummary *summary);
void BootMetadataSummary_ToPayload(const BootMetadataSummary *summary,
                                   uint16_t payload[BOOT_METADATA_SUMMARY_WORDS]);

#endif
