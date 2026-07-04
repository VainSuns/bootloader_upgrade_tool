#ifndef BOOT_FLASH_SERVICE_LIB_H
#define BOOT_FLASH_SERVICE_LIB_H

#include "boot_service_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

extern const BootServiceApi g_boot_flash_service_api;
extern uint16_t g_boot_flash_service_descriptor[BOOT_SERVICE_DESCRIPTOR_WORDS];
extern uint16_t g_boot_flash_service_crc_patch[2];

const BootServiceApi *BootFlashServiceLib_GetApi(void);
void BootFlashServiceLib_GetPatchSymbols(const BootServiceApi **api,
                                         uint16_t **descriptor,
                                         uint16_t **crc_patch);
void BootFlashServiceLib_BuildDescriptor(uint16_t *descriptor,
                                         uint32_t api_table_address,
                                         uint32_t image_start,
                                         uint32_t image_end_exclusive,
                                         uint32_t image_crc32);

#ifdef __cplusplus
}
#endif

#endif
