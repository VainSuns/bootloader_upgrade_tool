#include "boot_flash_service_private_lib.h"

uint16_t BootFlashService_MapResult(BootFlashResult result,
                                    uint16_t failed_status,
                                    uint16_t bad_address_status)
{
    switch (result)
    {
        case BOOT_FLASH_RESULT_OK:
            return BOOT_STATUS_OK;
        case BOOT_FLASH_RESULT_NOT_IMPLEMENTED:
            return BOOT_STATUS_UNSUPPORTED_FEATURE;
        case BOOT_FLASH_RESULT_BAD_ADDRESS:
            return bad_address_status;
        case BOOT_FLASH_RESULT_INIT_FAILED:
        case BOOT_FLASH_RESULT_FAILED:
        default:
            return failed_status;
    }
}

void BootFlashService_SetError(BootFlashServiceState *state,
                               BootErrorDetail *error,
                               uint16_t operation,
                               uint16_t stage,
                               uint32_t address,
                               uint32_t length_words,
                               uint16_t extra0,
                               uint16_t extra1)
{
    BootErrorDetail_Clear(error);
    error->operation = operation;
    error->stage = stage;
    error->address = address;
    error->length_words = length_words;
    error->extra0 = extra0;
    error->extra1 = extra1;
    if ((state != 0) && (state->core.set_last_error != 0))
    {
        state->core.set_last_error(state->core.ctx, error);
    }
}

void BootFlashService_SetFlashError(BootFlashServiceState *state,
                                    BootErrorDetail *error,
                                    uint16_t operation,
                                    uint16_t stage,
                                    BootFlashResult result,
                                    const BootFlashErrorInfo *info)
{
    BootFlashService_SetError(state,
                              error,
                              operation,
                              stage,
                              info->address,
                              info->length_words,
                              (uint16_t)(info->extra & 0xFFFFUL),
                              (uint16_t)(info->extra >> 16U));
    error->api_status = (uint16_t)info->api_status;
    if (error->api_status == 0U)
    {
        error->api_status = result;
    }
    error->fsm_status = info->fsm_status;
    if ((state != 0) && (state->core.set_last_error != 0))
    {
        state->core.set_last_error(state->core.ctx, error);
    }
}
