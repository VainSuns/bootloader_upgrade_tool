#ifndef BOOT_SERVICE_ABI_H
#define BOOT_SERVICE_ABI_H

#include <stdint.h>

#include "boot_device_info.h"
#include "boot_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

#define BOOT_SERVICE_API_MAGIC            ((uint32_t)0x42535631UL)
#define BOOT_SERVICE_ABI_MAJOR            ((uint16_t)1U)
#define BOOT_SERVICE_ABI_MINOR            ((uint16_t)0U)

#define BOOT_SERVICE_DESCRIPTOR_MAGIC     ((uint32_t)0x53564442UL)
#define BOOT_SERVICE_DESCRIPTOR_VERSION   ((uint16_t)1U)
#define BOOT_SERVICE_DESCRIPTOR_WORDS     ((uint16_t)20U)

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

/*
 * Descriptor word layout used by SERVICE_ATTACH:
 * 0-1 magic, 2 version, 3 descriptor_words, 4 abi_major, 5 abi_minor,
 * 6 service_major, 7 service_minor, 8-9 api_table_address,
 * 10-11 image_start, 12-13 image_end_exclusive, 14-15 image_crc32,
 * 16-17 capabilities, 18-19 crc32 over words 0..17.
 */

typedef struct
{
    uint16_t abi_major;
    uint16_t abi_minor;
    uint16_t size;
    const BootDeviceInfo *device_info;
    void (*set_last_error)(void *ctx, const BootErrorDetail *error);
    uint16_t (*check_ram_range)(void *ctx, uint32_t address, uint32_t word_count);
    void *ctx;
} BootCoreServices;

typedef struct
{
    uint32_t magic;
    uint16_t abi_major;
    uint16_t abi_minor;
    uint16_t size;
    uint16_t (*init)(const BootCoreServices *core_services);
    uint16_t (*handle_command)(const BootProtocolFrame *request,
                               uint16_t *response_payload,
                               uint16_t *response_payload_words,
                               BootErrorDetail *error);
    uint16_t (*deinit)(void);
} BootServiceApi;

#ifdef __cplusplus
}
#endif

#endif
