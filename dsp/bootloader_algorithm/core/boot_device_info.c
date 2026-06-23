#include "boot_device_info.h"

#include <stddef.h>

void BootDeviceInfo_ToPayload(const BootDeviceInfo *info,
                              uint16_t payload[BOOT_DEVICE_INFO_WORDS])
{
    payload[0] = info->device_id;
    payload[1] = info->cpu_id;
    payload[2] = info->kernel_ver_major;
    payload[3] = info->kernel_ver_minor;
    payload[4] = info->kernel_ver_patch;
    payload[5] = info->protocol_ver;
    payload[6] = (uint16_t)(info->feature_flags & 0xFFFFUL);
    payload[7] = (uint16_t)(info->feature_flags >> 16U);
    payload[8] = info->max_payload_words;
    payload[9] = info->max_data_words;
    payload[10] = info->boot_mode;
    payload[11] = info->kernel_layout;
    payload[12] = info->reserved[0];
    payload[13] = info->reserved[1];
    payload[14] = info->reserved[2];
    payload[15] = info->reserved[3];
}

void BootErrorDetail_Clear(BootErrorDetail *detail)
{
    detail->operation = BOOT_ERR_OP_NONE;
    detail->stage = BOOT_ERR_STAGE_NONE;
    detail->address = 0UL;
    detail->length_words = 0UL;
    detail->api_status = 0U;
    detail->fsm_status = 0UL;
    detail->extra0 = 0U;
    detail->extra1 = 0U;
}

void BootErrorDetail_ToPayload(const BootErrorDetail *detail,
                               uint16_t payload[BOOT_ERROR_DETAIL_WORDS])
{
    payload[0] = detail->operation;
    payload[1] = detail->stage;
    payload[2] = (uint16_t)(detail->address & 0xFFFFUL);
    payload[3] = (uint16_t)(detail->address >> 16U);
    payload[4] = (uint16_t)(detail->length_words & 0xFFFFUL);
    payload[5] = (uint16_t)(detail->length_words >> 16U);
    payload[6] = detail->api_status;
    payload[7] = (uint16_t)(detail->fsm_status & 0xFFFFUL);
    payload[8] = (uint16_t)(detail->fsm_status >> 16U);
    payload[9] = detail->extra0;
    payload[10] = detail->extra1;
}

