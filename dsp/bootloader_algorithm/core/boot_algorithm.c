#include "boot_algorithm.h"

#include <stddef.h>

static uint32_t BootAlgorithm_JoinU32(uint16_t low, uint16_t high)
{
    return ((uint32_t)high << 16U) | (uint32_t)low;
}

static void BootAlgorithm_ResetSession(BootAlgorithm *algorithm)
{
    algorithm->session.operation = BOOT_SESSION_NONE;
    algorithm->session.target = 0U;
    algorithm->session.expected_packet_count = 0UL;
    algorithm->session.processed_packet_count = 0UL;
    algorithm->session.expected_total_words = 0UL;
    algorithm->session.processed_total_words = 0UL;
    algorithm->session.expected_block_index = 0UL;
    algorithm->session.entry_point = 0UL;
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

static void BootAlgorithm_SetFlashError(BootAlgorithm *algorithm,
                                        uint16_t operation,
                                        uint16_t stage,
                                        BootFlashResult result,
                                        const BootFlashErrorInfo *info)
{
    BootAlgorithm_SetError(algorithm,
                           operation,
                           stage,
                           info->address,
                           info->length_words,
                           (uint16_t)(info->extra & 0xFFFFUL),
                           (uint16_t)(info->extra >> 16U));
    algorithm->last_error.api_status = (uint16_t)info->api_status;
    if (algorithm->last_error.api_status == 0U)
    {
        algorithm->last_error.api_status = result;
    }
    algorithm->last_error.fsm_status = info->fsm_status;
}

static uint16_t BootAlgorithm_MapFlashResult(BootFlashResult result,
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

static uint16_t BootAlgorithm_EnsureFlash(BootAlgorithm *algorithm,
                                          uint16_t operation,
                                          uint16_t failed_status)
{
    BootFlashErrorInfo info = {BOOT_FLASH_OP_NONE, 0UL, 0UL, 0L, 0UL, 0UL};
    BootFlashResult result;
    uint16_t status;

    if (algorithm->flash_initialized != 0U)
    {
        return BOOT_STATUS_OK;
    }
    info.operation = BOOT_FLASH_OP_NONE;
    result = BootFlash_Init(&info);
    status = BootAlgorithm_MapFlashResult(result,
                                          failed_status,
                                          BOOT_STATUS_BAD_ADDRESS);
    if (status != BOOT_STATUS_OK)
    {
        BootAlgorithm_SetFlashError(algorithm,
                                    operation,
                                    BOOT_ERR_STAGE_API_CALL,
                                    result,
                                    &info);
        return status;
    }
    algorithm->flash_initialized = 1U;
    return BOOT_STATUS_OK;
}

static uint16_t BootAlgorithm_IsKnownFutureCommand(uint16_t command)
{
    return (uint16_t)((command == BOOT_CMD_RAM_LOAD_BEGIN) ||
                      (command == BOOT_CMD_RAM_LOAD_DATA) ||
                      (command == BOOT_CMD_RAM_LOAD_END));
}

static void BootAlgorithm_Fail(BootAlgorithm *algorithm,
                               uint16_t status,
                               uint16_t operation,
                               uint16_t stage,
                               uint32_t address,
                               uint32_t length_words)
{
    BootAlgorithm_SetError(algorithm,
                           operation,
                           stage,
                           address,
                           length_words,
                           0U,
                           0U);
    BootAlgorithm_SendStatus(algorithm, status);
}

static void BootAlgorithm_HandleErase(BootAlgorithm *algorithm)
{
    BootFlashErrorInfo info = {BOOT_FLASH_OP_NONE, 0UL, 0UL, 0L, 0UL, 0UL};
    BootFlashResult result;
    uint32_t sector_mask;
    uint16_t status;

    if (algorithm->request.payload_words != 3U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           BOOT_ERR_OP_ERASE, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        return;
    }
    if (algorithm->request.payload[2] != 0U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_FLAGS,
                           BOOT_ERR_OP_ERASE, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        return;
    }
    sector_mask = BootAlgorithm_JoinU32(algorithm->request.payload[0],
                                        algorithm->request.payload[1]);
    if (sector_mask == 0UL)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_ADDRESS,
                           BOOT_ERR_OP_ERASE, BOOT_ERR_STAGE_ADDRESS_CHECK,
                           0UL, 0UL);
        return;
    }
    status = BootAlgorithm_EnsureFlash(algorithm,
                                       BOOT_ERR_OP_ERASE,
                                       BOOT_STATUS_ERASE_FAILED);
    if (status != BOOT_STATUS_OK)
    {
        BootAlgorithm_SendStatus(algorithm, status);
        return;
    }
    info.operation = BOOT_FLASH_OP_ERASE;
    info.extra = sector_mask;
    result = BootFlash_EraseBySectorMask(sector_mask, &info);
    status = BootAlgorithm_MapFlashResult(result,
                                          BOOT_STATUS_ERASE_FAILED,
                                          BOOT_STATUS_BAD_ADDRESS);
    if (status != BOOT_STATUS_OK)
    {
        BootAlgorithm_SetFlashError(algorithm, BOOT_ERR_OP_ERASE,
                                    BOOT_ERR_STAGE_API_CALL, result, &info);
        BootAlgorithm_SendStatus(algorithm, status);
        return;
    }
    BootAlgorithm_ResetSession(algorithm);
    algorithm->flash_modified = 1U;
    algorithm->verify_succeeded = 0U;
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

static void BootAlgorithm_HandleBegin(BootAlgorithm *algorithm,
                                      BootSessionOperation session_operation,
                                      uint16_t error_operation,
                                      uint16_t failed_status)
{
    uint32_t total_words;
    uint16_t status;

    if (algorithm->session.operation != BOOT_SESSION_NONE)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BUSY, error_operation,
                           BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return;
    }
    if (algorithm->request.payload_words != 9U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           error_operation, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        return;
    }
    if (algorithm->request.payload[8] != 0U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_FLAGS,
                           error_operation, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        return;
    }
    if (algorithm->request.payload[0] != BOOT_TARGET_FLASH_APP)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_TARGET_MISMATCH,
                           error_operation, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return;
    }
    total_words = BootAlgorithm_JoinU32(algorithm->request.payload[2],
                                        algorithm->request.payload[3]);
    if ((algorithm->request.payload[1] == 0U) || (total_words == 0UL))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_WORD_COUNT,
                           error_operation, BOOT_ERR_STAGE_PAYLOAD, 0UL,
                           total_words);
        return;
    }
    status = BootAlgorithm_EnsureFlash(algorithm, error_operation, failed_status);
    if (status != BOOT_STATUS_OK)
    {
        BootAlgorithm_SendStatus(algorithm, status);
        return;
    }
    algorithm->session.operation = session_operation;
    algorithm->session.target = BOOT_TARGET_FLASH_APP;
    algorithm->session.expected_packet_count = algorithm->request.payload[1];
    algorithm->session.processed_packet_count = 0UL;
    algorithm->session.expected_total_words = total_words;
    algorithm->session.processed_total_words = 0UL;
    algorithm->session.expected_block_index = 0UL;
    algorithm->session.entry_point =
        BootAlgorithm_JoinU32(algorithm->request.payload[4],
                              algorithm->request.payload[5]);
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

static void BootAlgorithm_HandleData(BootAlgorithm *algorithm,
                                     BootSessionOperation session_operation,
                                     uint16_t error_operation,
                                     BootFlashOperation flash_operation,
                                     uint16_t failed_status)
{
    BootFlashErrorInfo info = {BOOT_FLASH_OP_NONE, 0UL, 0UL, 0L, 0UL, 0UL};
    BootFlashResult result;
    uint32_t address;
    uint32_t block_index;
    uint16_t data_words;
    uint16_t status;
    uint16_t stage;

    if (algorithm->session.operation == BOOT_SESSION_NONE)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_MISSING_BEGIN,
                           error_operation, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return;
    }
    if (algorithm->session.operation != session_operation)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_INVALID_STATE,
                           error_operation, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return;
    }
    if (algorithm->request.payload_words < 5U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           error_operation, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        BootAlgorithm_ResetSession(algorithm);
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
                           error_operation, BOOT_ERR_STAGE_PAYLOAD,
                           address, data_words);
        BootAlgorithm_ResetSession(algorithm);
        return;
    }
    if ((data_words == 0U) || ((data_words % 8U) != 0U) ||
        (data_words > algorithm->device_info.max_data_words))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_WORD_COUNT,
                           error_operation, BOOT_ERR_STAGE_PAYLOAD,
                           address, data_words);
        BootAlgorithm_ResetSession(algorithm);
        return;
    }
    if (block_index != algorithm->session.expected_block_index)
    {
        BootAlgorithm_SetError(algorithm, error_operation, BOOT_ERR_STAGE_STATE,
                               address, data_words,
                               (uint16_t)(algorithm->session.expected_block_index & 0xFFFFUL),
                               (uint16_t)(algorithm->session.expected_block_index >> 16U));
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BLOCK_INDEX_ERROR);
        BootAlgorithm_ResetSession(algorithm);
        return;
    }
    if ((algorithm->session.processed_packet_count >=
         algorithm->session.expected_packet_count) ||
        ((uint32_t)data_words >
         algorithm->session.expected_total_words -
         algorithm->session.processed_total_words))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_TOTAL_COUNT_MISMATCH,
                           error_operation, BOOT_ERR_STAGE_STATE,
                           address, data_words);
        BootAlgorithm_ResetSession(algorithm);
        return;
    }
    info.operation = flash_operation;
    info.address = address;
    info.length_words = data_words;
    result = BootFlash_CheckAddress(address, data_words, flash_operation, &info);
    status = BootAlgorithm_MapFlashResult(result,
                                          failed_status,
                                          BOOT_STATUS_ADDRESS_OUT_OF_RANGE);
    if (status != BOOT_STATUS_OK)
    {
        BootAlgorithm_SetFlashError(algorithm, error_operation,
                                    BOOT_ERR_STAGE_ADDRESS_CHECK, result, &info);
        BootAlgorithm_SendStatus(algorithm, status);
        BootAlgorithm_ResetSession(algorithm);
        return;
    }
    if (session_operation == BOOT_SESSION_PROGRAM)
    {
        result = BootFlash_ProgramBlock(address,
                                        &algorithm->request.payload[5],
                                        data_words,
                                        &info);
        stage = BOOT_ERR_STAGE_API_CALL;
    }
    else
    {
        result = BootFlash_VerifyBlock(address,
                                       &algorithm->request.payload[5],
                                       data_words,
                                       &info);
        stage = BOOT_ERR_STAGE_VERIFY;
    }
    status = BootAlgorithm_MapFlashResult(result,
                                          failed_status,
                                          BOOT_STATUS_ADDRESS_OUT_OF_RANGE);
    if (status != BOOT_STATUS_OK)
    {
        BootAlgorithm_SetFlashError(algorithm, error_operation, stage, result, &info);
        BootAlgorithm_SendStatus(algorithm, status);
        BootAlgorithm_ResetSession(algorithm);
        return;
    }
    ++algorithm->session.processed_packet_count;
    algorithm->session.processed_total_words += data_words;
    ++algorithm->session.expected_block_index;
    if (session_operation == BOOT_SESSION_PROGRAM)
    {
        algorithm->flash_modified = 1U;
        algorithm->verify_succeeded = 0U;
    }
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

static void BootAlgorithm_HandleEnd(BootAlgorithm *algorithm,
                                    BootSessionOperation session_operation,
                                    uint16_t error_operation)
{
    uint32_t packet_count;
    uint32_t total_words;
    uint16_t valid;

    if (algorithm->session.operation == BOOT_SESSION_NONE)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_MISSING_BEGIN,
                           error_operation, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return;
    }
    if (algorithm->session.operation != session_operation)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_UNEXPECTED_END,
                           error_operation, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return;
    }
    if (algorithm->request.payload_words != 6U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           error_operation, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        BootAlgorithm_ResetSession(algorithm);
        return;
    }
    packet_count = BootAlgorithm_JoinU32(algorithm->request.payload[0],
                                         algorithm->request.payload[1]);
    total_words = BootAlgorithm_JoinU32(algorithm->request.payload[2],
                                        algorithm->request.payload[3]);
    valid = (uint16_t)((packet_count == algorithm->session.expected_packet_count) &&
                       (packet_count == algorithm->session.processed_packet_count) &&
                       (total_words == algorithm->session.expected_total_words) &&
                       (total_words == algorithm->session.processed_total_words));
    BootAlgorithm_ResetSession(algorithm);
    if (valid == 0U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_TOTAL_COUNT_MISMATCH,
                           error_operation, BOOT_ERR_STAGE_STATE, 0UL, total_words);
        return;
    }
    if (session_operation == BOOT_SESSION_VERIFY)
    {
        algorithm->verify_succeeded = 1U;
    }
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

static BootAlgorithmAction BootAlgorithm_HandleRun(BootAlgorithm *algorithm)
{
    BootFlashErrorInfo info = {BOOT_FLASH_OP_NONE, 0UL, 0UL, 0L, 0UL, 0UL};
    BootFlashResult result;
    uint32_t entry_point;
    uint16_t status;

    if (algorithm->request.payload_words != 4U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           BOOT_ERR_OP_RUN, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    if (algorithm->request.payload[3] != 0U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_FLAGS,
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
    if ((algorithm->flash_modified != 0U) &&
        (algorithm->verify_succeeded == 0U))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_INVALID_STATE,
                           BOOT_ERR_OP_RUN, BOOT_ERR_STAGE_STATE,
                           entry_point, 1UL);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    info.operation = BOOT_FLASH_OP_VERIFY;
    info.address = entry_point;
    info.length_words = 1UL;
    result = BootFlash_CheckAddress(entry_point, 1UL,
                                    BOOT_FLASH_OP_VERIFY, &info);
    status = BootAlgorithm_MapFlashResult(result,
                                          BOOT_STATUS_BAD_ADDRESS,
                                          BOOT_STATUS_ADDRESS_OUT_OF_RANGE);
    if (status != BOOT_STATUS_OK)
    {
        BootAlgorithm_SetFlashError(algorithm, BOOT_ERR_OP_RUN,
                                    BOOT_ERR_STAGE_ADDRESS_CHECK, result, &info);
        BootAlgorithm_SendStatus(algorithm, status);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
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
    BootAlgorithm_ResetSession(algorithm);
    algorithm->flash_initialized = 0U;
    algorithm->flash_modified = 0U;
    algorithm->verify_succeeded = 0U;
    return 1U;
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
            if (algorithm->request.payload_words != 0U)
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
            }
            else
            {
                BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
            }
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

        case BOOT_CMD_ERASE:
            BootAlgorithm_HandleErase(algorithm);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_PROGRAM_BEGIN:
            BootAlgorithm_HandleBegin(algorithm, BOOT_SESSION_PROGRAM,
                                      BOOT_ERR_OP_PROGRAM, BOOT_STATUS_PROGRAM_FAILED);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_PROGRAM_DATA:
            BootAlgorithm_HandleData(algorithm, BOOT_SESSION_PROGRAM,
                                     BOOT_ERR_OP_PROGRAM, BOOT_FLASH_OP_PROGRAM,
                                     BOOT_STATUS_PROGRAM_FAILED);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_PROGRAM_END:
            BootAlgorithm_HandleEnd(algorithm, BOOT_SESSION_PROGRAM,
                                    BOOT_ERR_OP_PROGRAM);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_VERIFY_BEGIN:
            BootAlgorithm_HandleBegin(algorithm, BOOT_SESSION_VERIFY,
                                      BOOT_ERR_OP_VERIFY, BOOT_STATUS_VERIFY_FAILED);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_VERIFY_DATA:
            BootAlgorithm_HandleData(algorithm, BOOT_SESSION_VERIFY,
                                     BOOT_ERR_OP_VERIFY, BOOT_FLASH_OP_VERIFY,
                                     BOOT_STATUS_VERIFY_FAILED);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_VERIFY_END:
            BootAlgorithm_HandleEnd(algorithm, BOOT_SESSION_VERIFY,
                                    BOOT_ERR_OP_VERIFY);
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
            BootAlgorithm_SendStatus(
                algorithm,
                BootAlgorithm_IsKnownFutureCommand(algorithm->request.command) != 0U ?
                BOOT_STATUS_UNSUPPORTED_COMMAND : BOOT_STATUS_UNKNOWN_COMMAND);
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
