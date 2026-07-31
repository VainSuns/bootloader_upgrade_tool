#ifndef BOOT_SERVICE_ABI_H
#define BOOT_SERVICE_ABI_H

#include <stdint.h>

#include "boot_flash_service_app_contract.h"
#include "boot_device_info.h"
#include "boot_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

#define BOOT_FLASH_SERVICE_HEADER_MAGIC          ((uint32_t)0x46534832UL)
#define BOOT_FLASH_SERVICE_ABI_MAJOR             ((uint16_t)2U)
#define BOOT_FLASH_SERVICE_ABI_MINOR             ((uint16_t)0U)
#define BOOT_FLASH_SERVICE_HEADER_VERSION        ((uint16_t)1U)
#define BOOT_FLASH_SERVICE_HEADER_WORDS          ((uint16_t)28U)
#define BOOT_FLASH_SERVICE_HEADER_RESERVED_WORDS ((uint16_t)0x20U)
#define BOOT_FLASH_SERVICE_CRC32_IEEE             ((uint16_t)1U)
#define BOOT_SERVICE_STATE_DETACHED       ((uint16_t)0x0000U)
#define BOOT_SERVICE_STATE_RAM_LOADED     ((uint16_t)0x0001U)
#define BOOT_SERVICE_STATE_ATTACHED       ((uint16_t)0x0002U)
#define BOOT_SERVICE_STATE_ERROR          ((uint16_t)0x0003U)

#define BOOT_SERVICE_CAP_ERASE            ((uint32_t)1UL << 0U)
#define BOOT_SERVICE_CAP_PROGRAM          ((uint32_t)1UL << 1U)
#define BOOT_SERVICE_CAP_VERIFY           ((uint32_t)1UL << 2U)
#define BOOT_SERVICE_CAP_METADATA_WRITE   ((uint32_t)1UL << 3U)
#define BOOT_SERVICE_REQUIRED_CAPABILITIES \
    (BOOT_SERVICE_CAP_ERASE | BOOT_SERVICE_CAP_PROGRAM | \
     BOOT_SERVICE_CAP_VERIFY | BOOT_SERVICE_CAP_METADATA_WRITE)

typedef uint16_t (*BootFlashServiceBootInitFn)(
    uint16_t device_id,
    uint16_t cpu_id,
    uint16_t max_data_words);

typedef uint16_t (*BootFlashServiceHandleCommandFn)(
    const BootProtocolFrame *request,
    uint16_t *response_payload,
    uint16_t *response_payload_words,
    BootErrorDetail *error);

typedef struct
{
    uint32_t magic;
    uint16_t header_version;
    uint16_t header_words;
    uint16_t abi_major;
    uint16_t abi_minor;
    uint32_t immutable_start;
    uint32_t immutable_end_exclusive;
    uint32_t publish_state_address;
    uint32_t runtime_state_address;
    uint32_t app_export_address;
    BootFlashServiceBootInitFn boot_init;
    BootFlashServiceHandleCommandFn boot_handle_command;
    uint32_t capabilities;
    uint16_t image_crc_algorithm;
    uint16_t reserved0;
    uint32_t immutable_image_crc32;
    uint32_t header_crc32;
} BootFlashServiceHeader;

#if defined(__TI_COMPILER_VERSION__)
typedef char BootFlashServiceHeaderWordsAssert[
    (sizeof(BootFlashServiceHeader) == BOOT_FLASH_SERVICE_HEADER_WORDS) ? 1 : -1];
#endif

#ifdef __cplusplus
}
#endif

#endif
