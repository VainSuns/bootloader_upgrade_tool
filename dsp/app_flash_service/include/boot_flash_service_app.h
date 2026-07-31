#ifndef BOOT_FLASH_SERVICE_APP_H
#define BOOT_FLASH_SERVICE_APP_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BOOT_FLASH_SERVICE_APP_STATUS_OK \
    ((uint16_t)0x0000U)

#define BOOT_FLASH_SERVICE_APP_STATUS_UNAVAILABLE \
    ((uint16_t)0x0801U)

uint16_t BootFlashServiceApp_IsAvailable(void);
uint16_t BootFlashServiceApp_ConfirmCurrentImage(void);

#ifdef __cplusplus
}
#endif

#endif
