#include "boot_algorithm.h"

#include <stddef.h>

#include "boot_protocol_core.h"
#include "boot_ram_port.h"

static uint32_t BootAlgorithm_JoinU32(uint16_t low, uint16_t high)
{
    return ((uint32_t)high << 16U) | (uint32_t)low;
}

static void BootAlgorithm_ResetRamLoad(BootAlgorithm *algorithm)
{
    algorithm->ram_load.active = 0U;
    algorithm->ram_load.target = 0U;
    algorithm->ram_load.expected_packet_count = 0UL;
    algorithm->ram_load.processed_packet_count = 0UL;
    algorithm->ram_load.expected_total_words = 0UL;
    algorithm->ram_load.processed_total_words = 0UL;
    algorithm->ram_load.expected_block_index = 0UL;
    algorithm->ram_load.entry_point = 0UL;
}

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

static void BootAlgorithm_SetLastError(void *ctx, const BootErrorDetail *error)
{
    BootAlgorithm *algorithm = (BootAlgorithm *)ctx;
    if ((algorithm != NULL) && (error != NULL))
    {
        algorithm->last_error = *error;
    }
}

static uint16_t BootAlgorithm_CheckRamRange(void *ctx,
                                            uint32_t address,
                                            uint32_t word_count)
{
    BootRamErrorInfo info = {0U, 0UL, 0UL, 0UL};
    (void)ctx;
    return (BootRam_CheckAddress(address, word_count, BOOT_TARGET_RAM_APP, &info) ==
            BOOT_RAM_RESULT_OK) ? 1U : 0U;
}

static void BootAlgorithm_SetError(BootAlgorithm *algorithm,
                                   uint16_t operation,
                                   uint16_t stage,
                                   uint32_t address,
                                   uint32_t length_words,
                                   uint16_t extra0,
                                   uint16_t extra1)
{
    BootErrorDetail_Clear(&algorithm->last_error);
    algorithm->last_error.operation = operation;
    algorithm->last_error.stage = stage;
    algorithm->last_error.address = address;
    algorithm->last_error.length_words = length_words;
    algorithm->last_error.extra0 = extra0;
    algorithm->last_error.extra1 = extra1;
}

static void BootAlgorithm_Fail(BootAlgorithm *algorithm,
                               uint16_t status,
                               uint16_t operation,
                               uint16_t stage,
                               uint32_t address,
                               uint32_t length_words)
{
    BootAlgorithm_SetError(algorithm, operation, stage, address, length_words, 0U, 0U);
    BootAlgorithm_SendStatus(algorithm, status);
}

static uint16_t BootAlgorithm_IsFlashCommand(uint16_t command)
{
    return (uint16_t)((command == BOOT_CMD_ERASE) ||
                      (command == BOOT_CMD_PROGRAM_BEGIN) ||
                      (command == BOOT_CMD_PROGRAM_DATA) ||
                      (command == BOOT_CMD_PROGRAM_END) ||
                      (command == BOOT_CMD_VERIFY_BEGIN) ||
                      (command == BOOT_CMD_VERIFY_DATA) ||
                      (command == BOOT_CMD_VERIFY_END));
}

static void BootAlgorithm_ForwardToService(BootAlgorithm *algorithm)
{
    uint16_t response_payload[BOOT_PROTOCOL_MAX_PAYLOAD_WORDS];
    uint16_t response_payload_words = 0U;
    BootErrorDetail error;
    uint16_t status;

    if ((algorithm->service_active == 0U) ||
        (algorithm->service_api == NULL) ||
        (algorithm->service_api->handle_command == NULL))
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_UNSUPPORTED_FEATURE);
        return;
    }

    BootErrorDetail_Clear(&error);
    status = algorithm->service_api->handle_command(&algorithm->request,
                                                    response_payload,
                                                    &response_payload_words,
                                                    &error);
    if (error.operation != BOOT_ERR_OP_NONE)
    {
        algorithm->last_error = error;
    }
    BootProtocol_SendResponse(&algorithm->io,
                              &algorithm->request,
                              (status == BOOT_STATUS_OK) ?
                              BOOT_PKT_RESPONSE : BOOT_PKT_ERROR_RESPONSE,
                              status,
                              response_payload,
                              response_payload_words);
}

static void BootAlgorithm_HandleRamLoadBegin(BootAlgorithm *algorithm)
{
    uint32_t total_words;
    uint16_t packets;
    uint32_t address;
    BootRamErrorInfo info = {0U, 0UL, 0UL, 0UL};

    if (algorithm->request.payload_words != 9U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        return;
    }
    if (algorithm->ram_load.active != 0U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BUSY,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return;
    }
    if (algorithm->request.payload[0] != BOOT_TARGET_RAM_APP)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_TARGET_MISMATCH,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return;
    }

    packets = algorithm->request.payload[1];
    total_words = BootAlgorithm_JoinU32(algorithm->request.payload[2],
                                        algorithm->request.payload[3]);
    address = BootAlgorithm_JoinU32(algorithm->request.payload[4],
                                    algorithm->request.payload[5]);
    if ((packets == 0U) || (total_words == 0UL))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_WORD_COUNT,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_PAYLOAD,
                           address, total_words);
        return;
    }
    if (BootRam_CheckAddress(address, total_words, BOOT_TARGET_RAM_APP, &info) !=
        BOOT_RAM_RESULT_OK)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_RAM_REGION_ERROR,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_ADDRESS_CHECK,
                           address, total_words);
        return;
    }

    algorithm->ram_load.active = 1U;
    algorithm->ram_load.target = BOOT_TARGET_RAM_APP;
    algorithm->ram_load.expected_packet_count = packets;
    algorithm->ram_load.processed_packet_count = 0UL;
    algorithm->ram_load.expected_total_words = total_words;
    algorithm->ram_load.processed_total_words = 0UL;
    algorithm->ram_load.expected_block_index = 0UL;
    algorithm->ram_load.entry_point = address;
    algorithm->service_image_ready = 0U;
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

static void BootAlgorithm_HandleRamLoadData(BootAlgorithm *algorithm)
{
    BootRamErrorInfo info = {0U, 0UL, 0UL, 0UL};
    uint32_t address;
    uint32_t block_index;
    uint16_t data_words;

    if (algorithm->ram_load.active == 0U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_MISSING_BEGIN,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return;
    }
    if (algorithm->request.payload_words < 5U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        BootAlgorithm_ResetRamLoad(algorithm);
        return;
    }

    address = BootAlgorithm_JoinU32(algorithm->request.payload[0],
                                    algorithm->request.payload[1]);
    data_words = algorithm->request.payload[2];
    block_index = BootAlgorithm_JoinU32(algorithm->request.payload[3],
                                        algorithm->request.payload[4]);
    if (algorithm->request.payload_words != (uint16_t)(5U + data_words))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_PAYLOAD,
                           address, data_words);
        BootAlgorithm_ResetRamLoad(algorithm);
        return;
    }
    if ((data_words == 0U) || ((data_words % 8U) != 0U) ||
        (data_words > algorithm->device_info.max_data_words))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_WORD_COUNT,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_PAYLOAD,
                           address, data_words);
        BootAlgorithm_ResetRamLoad(algorithm);
        return;
    }
    if (block_index != algorithm->ram_load.expected_block_index)
    {
        BootAlgorithm_SetError(algorithm, BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_STATE,
                               address, data_words,
                               (uint16_t)(algorithm->ram_load.expected_block_index & 0xFFFFUL),
                               (uint16_t)(algorithm->ram_load.expected_block_index >> 16U));
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BLOCK_INDEX_ERROR);
        BootAlgorithm_ResetRamLoad(algorithm);
        return;
    }
    if ((algorithm->ram_load.processed_packet_count >=
         algorithm->ram_load.expected_packet_count) ||
        ((uint32_t)data_words >
         algorithm->ram_load.expected_total_words -
         algorithm->ram_load.processed_total_words))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_TOTAL_COUNT_MISMATCH,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_STATE,
                           address, data_words);
        BootAlgorithm_ResetRamLoad(algorithm);
        return;
    }
    if (BootRam_WriteBlock(address, &algorithm->request.payload[5], data_words,
                           BOOT_TARGET_RAM_APP, &info) != BOOT_RAM_RESULT_OK)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_RAM_WRITE_FAILED,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_API_CALL,
                           address, data_words);
        BootAlgorithm_ResetRamLoad(algorithm);
        return;
    }

    ++algorithm->ram_load.processed_packet_count;
    algorithm->ram_load.processed_total_words += data_words;
    ++algorithm->ram_load.expected_block_index;
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

static void BootAlgorithm_HandleRamLoadEnd(BootAlgorithm *algorithm)
{
    uint32_t packets;
    uint32_t total_words;
    uint16_t valid;

    if (algorithm->ram_load.active == 0U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_MISSING_BEGIN,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return;
    }
    if (algorithm->request.payload_words != 6U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        BootAlgorithm_ResetRamLoad(algorithm);
        return;
    }

    packets = BootAlgorithm_JoinU32(algorithm->request.payload[0],
                                    algorithm->request.payload[1]);
    total_words = BootAlgorithm_JoinU32(algorithm->request.payload[2],
                                        algorithm->request.payload[3]);
    valid = (uint16_t)((packets == algorithm->ram_load.expected_packet_count) &&
                       (packets == algorithm->ram_load.processed_packet_count) &&
                       (total_words == algorithm->ram_load.expected_total_words) &&
                       (total_words == algorithm->ram_load.processed_total_words));
    BootAlgorithm_ResetRamLoad(algorithm);
    if (valid == 0U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_TOTAL_COUNT_MISMATCH,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_STATE, 0UL, total_words);
        return;
    }

    /* TODO(user port): validate the loaded image and attach its service API. */
    algorithm->service_image_ready = 1U;
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

static BootAlgorithmAction BootAlgorithm_HandleRun(BootAlgorithm *algorithm)
{
    uint32_t entry_point;

    if (algorithm->request.payload_words != 4U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           BOOT_ERR_OP_RUN, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    if (algorithm->request.payload[0] != BOOT_TARGET_FLASH_APP)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_TARGET_MISMATCH,
                           BOOT_ERR_OP_RUN, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    entry_point = BootAlgorithm_JoinU32(algorithm->request.payload[1],
                                        algorithm->request.payload[2]);
    if ((entry_point % 8UL) != 0UL)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_ALIGNMENT,
                           BOOT_ERR_OP_RUN, BOOT_ERR_STAGE_ADDRESS_CHECK,
                           entry_point, 1UL);
        return BOOT_ALGORITHM_ACTION_NONE;
    }

    algorithm->pending_entry_point = entry_point;
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
    return BOOT_ALGORITHM_ACTION_RUN_FLASH_APP;
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
    BootAlgorithm_ResetRamLoad(algorithm);
    algorithm->service_api = NULL;
    algorithm->service_active = 0U;
    algorithm->service_image_ready = 0U;
    algorithm->pending_entry_point = 0UL;
    algorithm->core_services.abi_major = BOOT_SERVICE_ABI_MAJOR;
    algorithm->core_services.abi_minor = BOOT_SERVICE_ABI_MINOR;
    algorithm->core_services.size = (uint16_t)sizeof(BootCoreServices);
    algorithm->core_services.device_info = &algorithm->device_info;
    algorithm->core_services.set_last_error = BootAlgorithm_SetLastError;
    algorithm->core_services.check_ram_range = BootAlgorithm_CheckRamRange;
    algorithm->core_services.ctx = algorithm;
    return 1U;
}

uint16_t BootAlgorithm_AttachService(BootAlgorithm *algorithm,
                                     const BootServiceApi *service_api)
{
    if ((algorithm == NULL) ||
        (service_api == NULL) ||
        (service_api->magic != BOOT_SERVICE_API_MAGIC) ||
        (service_api->abi_major != BOOT_SERVICE_ABI_MAJOR) ||
        (service_api->size != (uint16_t)sizeof(BootServiceApi)) ||
        (service_api->init == NULL) ||
        (service_api->handle_command == NULL) ||
        (service_api->init(&algorithm->core_services) == 0U))
    {
        return 0U;
    }
    algorithm->service_api = service_api;
    algorithm->service_active = 1U;
    return 1U;
}

uint32_t BootAlgorithm_GetPendingEntryPoint(const BootAlgorithm *algorithm)
{
    return (algorithm != NULL) ? algorithm->pending_entry_point : 0UL;
}

BootAlgorithmAction BootAlgorithm_ProcessOne(BootAlgorithm *algorithm)
{
    BootProtocolReceiveResult receive_result;
    uint16_t payload[BOOT_DEVICE_INFO_WORDS];

    receive_result = BootProtocol_Receive(&algorithm->io, &algorithm->request);
    if (receive_result == BOOT_PROTOCOL_RECEIVE_BAD_PAYLOAD_CRC)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_CRC);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    if (algorithm->request.protocol_ver != BOOT_PROTOCOL_VERSION)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_UNSUPPORTED_PROTOCOL);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    if (algorithm->request.packet_type != BOOT_PKT_REQUEST)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PACKET_TYPE);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    if (algorithm->request.flags != BOOT_PROTOCOL_FLAG_NONE)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_FLAGS);
        return BOOT_ALGORITHM_ACTION_NONE;
    }

    switch (algorithm->request.command)
    {
        case BOOT_CMD_PING:
            BootAlgorithm_SendStatus(
                algorithm,
                (algorithm->request.payload_words == 0U) ?
                BOOT_STATUS_OK : BOOT_STATUS_BAD_PAYLOAD_LENGTH);
            return BOOT_ALGORITHM_ACTION_NONE;

        case BOOT_CMD_GET_DEVICE_INFO:
            if (algorithm->request.payload_words != 0U)
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
                return BOOT_ALGORITHM_ACTION_NONE;
            }
            BootDeviceInfo_ToPayload(&algorithm->device_info, payload);
            BootProtocol_SendResponse(&algorithm->io, &algorithm->request,
                                      BOOT_PKT_RESPONSE, BOOT_STATUS_OK,
                                      payload, BOOT_DEVICE_INFO_WORDS);
            return BOOT_ALGORITHM_ACTION_NONE;

        case BOOT_CMD_GET_PROTOCOL_INFO:
            if (algorithm->request.payload_words != 0U)
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
                return BOOT_ALGORITHM_ACTION_NONE;
            }
            payload[0] = BOOT_PROTOCOL_VERSION;
            payload[1] = BOOT_PROTOCOL_VERSION;
            payload[2] = BOOT_PROTOCOL_VERSION;
            payload[3] = BOOT_PROTOCOL_HEADER_WORDS;
            payload[4] = 0x0001U;
            payload[5] = 0x0001U;
            payload[6] = algorithm->device_info.max_payload_words;
            payload[7] = 0U;
            BootProtocol_SendResponse(&algorithm->io, &algorithm->request,
                                      BOOT_PKT_RESPONSE, BOOT_STATUS_OK,
                                      payload, BOOT_PROTOCOL_INFO_WORDS);
            return BOOT_ALGORITHM_ACTION_NONE;

        case BOOT_CMD_GET_LAST_ERROR:
            if (algorithm->request.payload_words != 0U)
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
                return BOOT_ALGORITHM_ACTION_NONE;
            }
            BootErrorDetail_ToPayload(&algorithm->last_error, payload);
            BootProtocol_SendResponse(&algorithm->io, &algorithm->request,
                                      BOOT_PKT_RESPONSE, BOOT_STATUS_OK,
                                      payload, BOOT_ERROR_DETAIL_WORDS);
            return BOOT_ALGORITHM_ACTION_NONE;

        case BOOT_CMD_RAM_LOAD_BEGIN:
            BootAlgorithm_HandleRamLoadBegin(algorithm);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_RAM_LOAD_DATA:
            BootAlgorithm_HandleRamLoadData(algorithm);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_RAM_LOAD_END:
            BootAlgorithm_HandleRamLoadEnd(algorithm);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_RUN:
            return BootAlgorithm_HandleRun(algorithm);
        case BOOT_CMD_RESET:
            if (algorithm->request.payload_words != 0U)
            {
                BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                                   BOOT_ERR_OP_RESET, BOOT_ERR_STAGE_PAYLOAD,
                                   0UL, 0UL);
                return BOOT_ALGORITHM_ACTION_NONE;
            }
            BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
            return BOOT_ALGORITHM_ACTION_RESET_DEVICE;
        default:
            if (BootAlgorithm_IsFlashCommand(algorithm->request.command) != 0U)
            {
                BootAlgorithm_ForwardToService(algorithm);
            }
            else
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_UNKNOWN_COMMAND);
            }
            return BOOT_ALGORITHM_ACTION_NONE;
    }
}

BootAlgorithmAction BootAlgorithm_Run(BootAlgorithm *algorithm)
{
    BootAlgorithmAction action;
    for (;;)
    {
        action = BootAlgorithm_ProcessOne(algorithm);
        if (action != BOOT_ALGORITHM_ACTION_NONE)
        {
            return action;
        }
    }
}
