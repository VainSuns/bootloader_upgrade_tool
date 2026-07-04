#ifndef BOOT_FLASH_SERVICE_LIB_H
#define BOOT_FLASH_SERVICE_LIB_H

#include "boot_service_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

const BootServiceApi *BootFlashServiceLib_GetApi(void);
void BootFlashServiceLib_BuildDescriptor(uint16_t *descriptor,
                                         uint32_t api_table_address,
                                         uint32_t image_start,
                                         uint32_t image_end_exclusive,
                                         uint32_t image_crc32);

#ifdef __cplusplus
}
#endif

#endif
