#ifndef BOOT_FLASH_SERVICE_LIB_H
#define BOOT_FLASH_SERVICE_LIB_H

#include "boot_service_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

extern const BootFlashServiceHeader g_boot_flash_service_header;
extern BootFlashServicePublishState g_boot_flash_service_publish_state;
extern const BootFlashServiceAppExport g_boot_flash_service_app_export;

uint16_t BootFlashService_BootInit(uint16_t device_id,
                                   uint16_t cpu_id,
                                   uint16_t max_data_words);
uint16_t BootFlashService_BootHandleCommand(const BootProtocolFrame *request,
                                            uint16_t *response_payload,
                                            uint16_t *response_payload_words,
                                            BootErrorDetail *error);
uint16_t BootFlashService_ConfirmCurrentImage(void);

#ifdef __cplusplus
}
#endif

#endif
