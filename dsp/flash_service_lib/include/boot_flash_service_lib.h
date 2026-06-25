#ifndef BOOT_FLASH_SERVICE_LIB_H
#define BOOT_FLASH_SERVICE_LIB_H

#include "boot_service_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

const BootServiceApi *BootFlashServiceLib_GetApi(void);

#ifdef __cplusplus
}
#endif

#endif
