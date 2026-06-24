#include "boot_algorithm.h"

#include <stddef.h>

static void BootAlgorithm_SendStatus(BootAlgorithm *algorithm, uint16_t status)
{
    uint16_t packet_type = (status == BOOT_STATUS_OK) ?
                           BOOT_PKT_RESPONSE : BOOT_PKT_ERROR_RESPONSE;
    BootProtocol_SendResponse(&algorithm->io,
                              &algorithm->request,
                              packet_type,
                              status,
                              NULL,
                              0U);
}

static uint16_t BootAlgorithm_IsKnownNonCoreCommand(uint16_t command)
{
    switch (command)
    {
        case BOOT_CMD_RAM_LOAD_BEGIN:
        case BOOT_CMD_RAM_LOAD_DATA:
        case BOOT_CMD_RAM_LOAD_END:
        case BOOT_CMD_ERASE:
        case BOOT_CMD_PROGRAM_BEGIN:
        case BOOT_CMD_PROGRAM_DATA:
        case BOOT_CMD_PROGRAM_END:
        case BOOT_CMD_VERIFY_BEGIN:
        case BOOT_CMD_VERIFY_DATA:
        case BOOT_CMD_VERIFY_END:
        case BOOT_CMD_RUN:
        case BOOT_CMD_RESET:
            return 1U;
        default:
            return 0U;
    }
}

uint16_t BootAlgorithm_Init(BootAlgorithm *algorithm,
                            const BootIoOps *io,
                            const BootDeviceInfo *device_info)
{
    if ((algorithm == NULL) || (device_info == NULL) || (BootIo_IsValid(io) == 0U))
    {
        return 0U;
    }
    if ((device_info->protocol_ver != BOOT_PROTOCOL_VERSION) ||
        (device_info->max_payload_words > BOOT_PROTOCOL_MAX_PAYLOAD_WORDS) ||
        (device_info->max_data_words == 0U) ||
        ((device_info->max_data_words % 8U) != 0U) ||
        ((uint32_t)device_info->max_data_words + 5UL >
         (uint32_t)device_info->max_payload_words))
    {
        return 0U;
    }
    algorithm->io = *io;
    algorithm->device_info = *device_info;
    BootErrorDetail_Clear(&algorithm->last_error);
    return 1U;
}

void BootAlgorithm_ProcessOne(BootAlgorithm *algorithm)
{
    BootProtocolReceiveResult receive_result;
    uint16_t payload[BOOT_DEVICE_INFO_WORDS];

    receive_result = BootProtocol_Receive(&algorithm->io, &algorithm->request);
    if (receive_result == BOOT_PROTOCOL_RECEIVE_BAD_PAYLOAD_CRC)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_CRC);
        return;
    }
    if (algorithm->request.protocol_ver != BOOT_PROTOCOL_VERSION)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_UNSUPPORTED_PROTOCOL);
        return;
    }
    if (algorithm->request.packet_type != BOOT_PKT_REQUEST)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PACKET_TYPE);
        return;
    }
    if (algorithm->request.flags != BOOT_PROTOCOL_FLAG_NONE)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_FLAGS);
        return;
    }

    switch (algorithm->request.command)
    {
        case BOOT_CMD_PING:
            if (algorithm->request.payload_words != 0U)
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
                return;
            }
            BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
            return;

        case BOOT_CMD_GET_DEVICE_INFO:
            if (algorithm->request.payload_words != 0U)
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
                return;
            }
            BootDeviceInfo_ToPayload(&algorithm->device_info, payload);
            BootProtocol_SendResponse(&algorithm->io,
                                      &algorithm->request,
                                      BOOT_PKT_RESPONSE,
                                      BOOT_STATUS_OK,
                                      payload,
                                      BOOT_DEVICE_INFO_WORDS);
            return;

        case BOOT_CMD_GET_PROTOCOL_INFO:
            if (algorithm->request.payload_words != 0U)
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
                return;
            }
            payload[0] = BOOT_PROTOCOL_VERSION;
            payload[1] = BOOT_PROTOCOL_VERSION;
            payload[2] = BOOT_PROTOCOL_VERSION;
            payload[3] = BOOT_PROTOCOL_HEADER_WORDS;
            payload[4] = 0x0001U;
            payload[5] = 0x0001U;
            payload[6] = algorithm->device_info.max_payload_words;
            payload[7] = 0U;
            BootProtocol_SendResponse(&algorithm->io,
                                      &algorithm->request,
                                      BOOT_PKT_RESPONSE,
                                      BOOT_STATUS_OK,
                                      payload,
                                      BOOT_PROTOCOL_INFO_WORDS);
            return;

        case BOOT_CMD_GET_LAST_ERROR:
            if (algorithm->request.payload_words != 0U)
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
                return;
            }
            BootErrorDetail_ToPayload(&algorithm->last_error, payload);
            BootProtocol_SendResponse(&algorithm->io,
                                      &algorithm->request,
                                      BOOT_PKT_RESPONSE,
                                      BOOT_STATUS_OK,
                                      payload,
                                      BOOT_ERROR_DETAIL_WORDS);
            return;

        default:
            if (BootAlgorithm_IsKnownNonCoreCommand(algorithm->request.command) != 0U)
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_UNSUPPORTED_COMMAND);
            }
            else
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_UNKNOWN_COMMAND);
            }
            return;
    }
}

void BootAlgorithm_Run(BootAlgorithm *algorithm)
{
    for (;;)
    {
        BootAlgorithm_ProcessOne(algorithm);
    }
}
