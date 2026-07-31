#include "boot_flash_service_app.h"
#include "boot_flash_service_layout.h"
#include "boot_flash_service_app_contract.h"

#ifndef BOOT_FLASH_SERVICE_APP_GET_PUBLISH_STATE
#define BOOT_FLASH_SERVICE_APP_GET_PUBLISH_STATE() \
    ((const volatile BootFlashServicePublishState *)(uintptr_t) \
        BOOT_FLASH_SERVICE_PUBLISH_ORIGIN)
#endif

#ifndef BOOT_FLASH_SERVICE_APP_GET_EXPORT
#define BOOT_FLASH_SERVICE_APP_GET_EXPORT() \
    ((const BootFlashServiceAppExport *)(uintptr_t) \
        BOOT_FLASH_SERVICE_APP_EXPORT_ORIGIN)
#endif

uint16_t BootFlashServiceApp_IsAvailable(void)
{
    const volatile BootFlashServicePublishState *publish_state =
        BOOT_FLASH_SERVICE_APP_GET_PUBLISH_STATE();

    return ((publish_state->valid == BOOT_FLASH_SERVICE_PUBLISH_VALID) &&
            (publish_state->valid_inverse ==
             BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE)) ? 1U : 0U;
}

uint16_t BootFlashServiceApp_ConfirmCurrentImage(void)
{
    const BootFlashServiceAppExport *app_export;

    if (BootFlashServiceApp_IsAvailable() == 0U)
    {
        return BOOT_FLASH_SERVICE_APP_STATUS_UNAVAILABLE;
    }

    app_export = BOOT_FLASH_SERVICE_APP_GET_EXPORT();
    return app_export->confirm_current_image();
}
