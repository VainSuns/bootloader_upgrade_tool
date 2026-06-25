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
