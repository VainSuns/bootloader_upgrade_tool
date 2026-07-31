#ifndef BOOT_FLASH_SERVICE_APP_CONTRACT_H
#define BOOT_FLASH_SERVICE_APP_CONTRACT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BOOT_FLASH_SERVICE_PUBLISH_VALID \
    ((uint16_t)0xA55AU)

#define BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE \
    ((uint16_t)0x5AA5U)

#define BOOT_FLASH_SERVICE_PUBLISH_INVALID \
    ((uint16_t)0x0000U)

typedef uint16_t (*BootFlashServiceConfirmFn)(void);

typedef struct
{
    volatile uint16_t valid;
    volatile uint16_t valid_inverse;
} BootFlashServicePublishState;

typedef struct
{
    BootFlashServiceConfirmFn confirm_current_image;
} BootFlashServiceAppExport;

#ifdef __cplusplus
}
#endif

#endif
