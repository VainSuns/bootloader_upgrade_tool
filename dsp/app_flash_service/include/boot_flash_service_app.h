#ifndef BOOT_FLASH_SERVICE_APP_H
#define BOOT_FLASH_SERVICE_APP_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

uint16_t BootFlashServiceApp_IsAvailable(void);
uint16_t BootFlashServiceApp_ConfirmCurrentImage(void);

#ifdef __cplusplus
}
#endif

#endif
