#include "boot_algorithm.h"

#include <stddef.h>

#include "boot_crc32.h"
#include "boot_metadata.h"
#include "boot_protocol_core.h"
#include "boot_ram_port.h"
#include "boot_user_config.h"
#include "boot_user_feature_config.h"

#ifndef BOOT_SERVICE_READ_WORD
#define BOOT_SERVICE_READ_WORD(address) (*(const volatile uint16_t *)(uintptr_t)(address))
#endif

#ifndef BOOT_SERVICE_WRITE_WORD
#define BOOT_SERVICE_WRITE_WORD(address, value) \
    (*(volatile uint16_t *)(uintptr_t)(address) = (value))
#endif

#ifndef BOOT_SERVICE_BOOT_INIT_FROM_ADDRESS
#define BOOT_SERVICE_BOOT_INIT_FROM_ADDRESS(address) \
    ((BootFlashServiceBootInitFn)(uintptr_t)(address))
#endif

#ifndef BOOT_SERVICE_HANDLE_COMMAND_FROM_ADDRESS
#define BOOT_SERVICE_HANDLE_COMMAND_FROM_ADDRESS(address) \
    ((BootFlashServiceHandleCommandFn)(uintptr_t)(address))
#endif

#if BOOT_ENABLE_MEMORY_READ
#ifndef BOOT_MEMORY_READ_WORD
#define BOOT_MEMORY_READ_WORD(address) (*(const volatile uint16_t *)(uintptr_t)(address))
#endif
#endif

static uint32_t BootAlgorithm_JoinU32(uint16_t low, uint16_t high)
{
    return ((uint32_t)high << 16U) | (uint32_t)low;
}

static void BootAlgorithm_SplitU32(uint32_t value, uint16_t *low, uint16_t *high)
{
    *low = (uint16_t)(value & 0xFFFFUL);
    *high = (uint16_t)(value >> 16U);
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
    algorithm->ram_load.loaded_start = 0UL;
    algorithm->ram_load.loaded_end_exclusive = 0UL;
    algorithm->ram_load.crc32 = BOOT_CRC32_INIT_VALUE;
    algorithm->ram_load.image_ready = 0U;
    algorithm->ram_load.crc_checked = 0U;
}

static void BootAlgorithm_ResetServiceState(BootAlgorithm *algorithm)
{
    algorithm->service_command_handler = NULL;
    algorithm->service_active = 0U;
    algorithm->service_state.state = BOOT_SERVICE_STATE_DETACHED;
    algorithm->service_state.last_attach_status = BOOT_STATUS_OK;
    algorithm->service_state.capabilities = 0UL;
    algorithm->service_state.loaded_crc32 = 0UL;
    algorithm->service_state.loaded_words = 0UL;
}

static void BootAlgorithm_InvalidatePublishState(void)
{
    BOOT_SERVICE_WRITE_WORD(BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS,
                            BOOT_FLASH_SERVICE_PUBLISH_INVALID);
    BOOT_SERVICE_WRITE_WORD(BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS + 1UL,
                            BOOT_FLASH_SERVICE_PUBLISH_INVALID);
}

static void BootAlgorithm_InvalidateFlashService(BootAlgorithm *algorithm)
{
    BootAlgorithm_InvalidatePublishState();
    algorithm->service_command_handler = NULL;
    algorithm->service_active = 0U;
    algorithm->service_state.state = BOOT_SERVICE_STATE_DETACHED;
    algorithm->service_state.capabilities = 0UL;
}

uint16_t BootAlgorithm_ValidateFlashService(
    const BootDeviceInfo *device_info,
    BootFlashServiceHandleCommandFn *command_handler)
{
    uint16_t header[BOOT_FLASH_SERVICE_HEADER_WORDS];
    uint32_t immutable_start;
    uint32_t immutable_end;
    uint32_t publish_address;
    uint32_t runtime_state_address;
    uint32_t app_export_address;
    uint32_t confirm_current_image_address;
    uint32_t boot_init_address;
    uint32_t command_address;
    uint32_t capabilities;
    uint32_t expected_crc32;
    uint32_t crc32;
    uint32_t address;
    uint16_t status;
    uint16_t index;
    BootRamErrorInfo ram_error = {0U, 0UL, 0UL, 0UL};
    BootFlashServiceBootInitFn boot_init;
    BootFlashServiceHandleCommandFn validated_handler;

    BootAlgorithm_InvalidatePublishState();
    if (command_handler != NULL)
    {
        *command_handler = NULL;
    }
    if (device_info == NULL)
    {
        return BOOT_STATUS_INVALID_STATE;
    }

    for (index = 0U; index < BOOT_FLASH_SERVICE_HEADER_WORDS; ++index)
    {
        header[index] = BOOT_SERVICE_READ_WORD(
            BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + (uint32_t)index);
    }
    if ((BootAlgorithm_JoinU32(header[0], header[1]) !=
         BOOT_FLASH_SERVICE_HEADER_MAGIC) ||
        (header[2] != BOOT_FLASH_SERVICE_HEADER_VERSION) ||
        (header[3] != BOOT_FLASH_SERVICE_HEADER_WORDS) ||
        (BootCrc32_CalcWords(header,
                             (uint32_t)BOOT_FLASH_SERVICE_HEADER_WORDS - 2UL) !=
         BootAlgorithm_JoinU32(header[26], header[27])))
    {
        return BOOT_STATUS_METADATA_INVALID;
    }
    if ((header[4] != BOOT_FLASH_SERVICE_ABI_MAJOR) ||
        (header[5] > BOOT_FLASH_SERVICE_ABI_MINOR) ||
        (header[22] != BOOT_FLASH_SERVICE_CRC32_IEEE))
    {
        return BOOT_STATUS_UNSUPPORTED_PROTOCOL;
    }

    immutable_start = BootAlgorithm_JoinU32(header[6], header[7]);
    immutable_end = BootAlgorithm_JoinU32(header[8], header[9]);
    publish_address = BootAlgorithm_JoinU32(header[10], header[11]);
    runtime_state_address = BootAlgorithm_JoinU32(header[12], header[13]);
    app_export_address = BootAlgorithm_JoinU32(header[14], header[15]);
    boot_init_address = BootAlgorithm_JoinU32(header[16], header[17]);
    command_address = BootAlgorithm_JoinU32(header[18], header[19]);
    capabilities = BootAlgorithm_JoinU32(header[20], header[21]);
    expected_crc32 = BootAlgorithm_JoinU32(header[24], header[25]);

    if ((publish_address != BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS) ||
        (runtime_state_address != BOOT_FLASH_SERVICE_RUNTIME_ORIGIN) ||
        (app_export_address != BOOT_FLASH_SERVICE_APP_EXPORT_ORIGIN) ||
        (immutable_start != app_export_address))
    {
        return BOOT_STATUS_METADATA_INVALID;
    }
    if ((immutable_start < (BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS +
                            BOOT_FLASH_SERVICE_HEADER_RESERVED_WORDS)) ||
        (immutable_end <= immutable_start) ||
        (BootRam_CheckAddress(immutable_start,
                              immutable_end - immutable_start,
                              BOOT_TARGET_RAM_APP,
                              &ram_error) != BOOT_RAM_RESULT_OK) ||
        (boot_init_address < immutable_start) ||
        (boot_init_address >= immutable_end) ||
        (command_address < immutable_start) ||
        (command_address >= immutable_end))
    {
        return BOOT_STATUS_RAM_REGION_ERROR;
    }
    confirm_current_image_address = BootAlgorithm_JoinU32(
        BOOT_SERVICE_READ_WORD(app_export_address),
        BOOT_SERVICE_READ_WORD(app_export_address + 1UL));
    if ((confirm_current_image_address == 0UL) ||
        (confirm_current_image_address == 0xFFFFFFFFUL) ||
        (confirm_current_image_address < immutable_start) ||
        (confirm_current_image_address >= immutable_end))
    {
        return BOOT_STATUS_RAM_REGION_ERROR;
    }
    if ((capabilities & BOOT_SERVICE_REQUIRED_CAPABILITIES) !=
        BOOT_SERVICE_REQUIRED_CAPABILITIES)
    {
        return BOOT_STATUS_UNSUPPORTED_FEATURE;
    }

    crc32 = BOOT_CRC32_INIT_VALUE;
    for (address = immutable_start; address < immutable_end; ++address)
    {
        crc32 = BootCrc32_UpdateWord(crc32, BOOT_SERVICE_READ_WORD(address));
    }
    if (BootCrc32_Finalize(crc32) != expected_crc32)
    {
        return BOOT_STATUS_VERIFY_MISMATCH;
    }

    boot_init = BOOT_SERVICE_BOOT_INIT_FROM_ADDRESS(boot_init_address);
    validated_handler =
        BOOT_SERVICE_HANDLE_COMMAND_FROM_ADDRESS(command_address);
    if ((boot_init == NULL) || (validated_handler == NULL))
    {
        return BOOT_STATUS_RAM_REGION_ERROR;
    }
    status = boot_init(device_info->device_id,
                       device_info->cpu_id,
                       device_info->max_data_words);
    if (status != BOOT_STATUS_OK)
    {
        return status;
    }

    if (command_handler != NULL)
    {
        *command_handler = validated_handler;
    }
    BOOT_SERVICE_WRITE_WORD(BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS + 1UL,
                            BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE);
    BOOT_SERVICE_WRITE_WORD(BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS,
                            BOOT_FLASH_SERVICE_PUBLISH_VALID);
    return BOOT_STATUS_OK;
}

static uint16_t BootAlgorithm_RangeOverlapsFlashService(uint32_t address,
                                                        uint32_t word_count)
{
    uint32_t end_exclusive = address + word_count;
    uint32_t service_end_exclusive = BOOT_FLASH_SERVICE_DATA_ORIGIN +
                                     BOOT_FLASH_SERVICE_DATA_LENGTH;
    return (uint16_t)((word_count != 0UL) &&
                      (end_exclusive >= address) &&
                      (address < service_end_exclusive) &&
                      (end_exclusive > BOOT_FLASH_SERVICE_HEADER_ORIGIN));
}

static uint16_t BootAlgorithm_IsRangeInLoadedRamImage(const BootAlgorithm *algorithm,
                                                      uint32_t address,
                                                      uint32_t word_count)
{
    uint32_t end_exclusive = address + word_count;
    return (uint16_t)((word_count != 0UL) &&
                      (end_exclusive >= address) &&
                      (algorithm->ram_load.image_ready != 0U) &&
                      (address >= algorithm->ram_load.loaded_start) &&
                      (end_exclusive <= algorithm->ram_load.loaded_end_exclusive));
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

#if BOOT_ENABLE_RUN_RAM
static uint16_t BootAlgorithm_IsInLoadedRamImage(const BootAlgorithm *algorithm,
                                                 uint32_t entry_point)
{
    return BootAlgorithm_IsRangeInLoadedRamImage(algorithm, entry_point, 1UL);
}
#endif

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
                      (command == BOOT_CMD_VERIFY_END) ||
                      (command == BOOT_CMD_METADATA_APPEND_RECORD));
}

static void BootAlgorithm_ForwardToService(BootAlgorithm *algorithm)
{
    uint16_t response_payload[BOOT_PROTOCOL_MAX_PAYLOAD_WORDS];
    uint16_t response_payload_words = 0U;
    BootErrorDetail error;
    uint16_t status;

    if ((algorithm->service_active == 0U) ||
        (algorithm->service_command_handler == NULL))
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_UNSUPPORTED_FEATURE);
        return;
    }

    BootErrorDetail_Clear(&error);
    status = algorithm->service_command_handler(&algorithm->request,
                                                response_payload,
                                                &response_payload_words,
                                                &error);
    if (error.operation != BOOT_ERR_OP_NONE)
    {
        algorithm->last_error = error;
    }
    if ((response_payload_words > algorithm->device_info.max_payload_words) ||
        (response_payload_words > BOOT_PROTOCOL_MAX_PAYLOAD_WORDS))
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
        return;
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
    uint32_t entry_point;
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
    entry_point = BootAlgorithm_JoinU32(algorithm->request.payload[4],
                                        algorithm->request.payload[5]);
    if ((packets == 0U) || (total_words == 0UL))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_WORD_COUNT,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_PAYLOAD,
                           entry_point, total_words);
        return;
    }
    if (BootRam_CheckAddress(entry_point, 1UL, BOOT_TARGET_RAM_APP, &info) !=
        BOOT_RAM_RESULT_OK)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_RAM_REGION_ERROR,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_ADDRESS_CHECK,
                           entry_point, 1UL);
        return;
    }

    algorithm->ram_load.active = 1U;
    algorithm->ram_load.target = BOOT_TARGET_RAM_APP;
    algorithm->ram_load.expected_packet_count = packets;
    algorithm->ram_load.processed_packet_count = 0UL;
    algorithm->ram_load.expected_total_words = total_words;
    algorithm->ram_load.processed_total_words = 0UL;
    algorithm->ram_load.expected_block_index = 0UL;
    algorithm->ram_load.entry_point = entry_point;
    algorithm->ram_load.loaded_start = 0xFFFFFFFFUL;
    algorithm->ram_load.loaded_end_exclusive = 0UL;
    algorithm->ram_load.crc32 = BOOT_CRC32_INIT_VALUE;
    algorithm->ram_load.image_ready = 0U;
    algorithm->ram_load.crc_checked = 0U;
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

static void BootAlgorithm_HandleRamLoadData(BootAlgorithm *algorithm)
{
    BootRamErrorInfo info = {0U, 0UL, 0UL, 0UL};
    uint32_t address;
    uint32_t block_index;
    uint16_t data_words;
    BootRamResult ram_result;
    uint16_t index;

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
    if (data_words == 0U)
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
    if (BootAlgorithm_RangeOverlapsFlashService(address, data_words) != 0U)
    {
        BootAlgorithm_InvalidateFlashService(algorithm);
    }
    ram_result = BootRam_WriteBlock(address, &algorithm->request.payload[5], data_words,
                                    BOOT_TARGET_RAM_APP, &info);
    if (ram_result != BOOT_RAM_RESULT_OK)
    {
        BootAlgorithm_Fail(algorithm,
                           (ram_result == BOOT_RAM_RESULT_BAD_ADDRESS) ?
                           BOOT_STATUS_RAM_REGION_ERROR : BOOT_STATUS_RAM_WRITE_FAILED,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_API_CALL,
                           address, data_words);
        BootAlgorithm_ResetRamLoad(algorithm);
        return;
    }
    if (BootAlgorithm_RangeOverlapsFlashService(address, data_words) != 0U)
    {
        BootAlgorithm_InvalidatePublishState();
    }

    ++algorithm->ram_load.processed_packet_count;
    algorithm->ram_load.processed_total_words += data_words;
    ++algorithm->ram_load.expected_block_index;
    for (index = 0U; index < data_words; index++)
    {
        algorithm->ram_load.crc32 =
            BootCrc32_UpdateWord(algorithm->ram_load.crc32,
                                 algorithm->request.payload[5U + index]);
    }
    if (address < algorithm->ram_load.loaded_start)
    {
        algorithm->ram_load.loaded_start = address;
    }
    if ((address + (uint32_t)data_words) > algorithm->ram_load.loaded_end_exclusive)
    {
        algorithm->ram_load.loaded_end_exclusive = address + (uint32_t)data_words;
    }
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

static void BootAlgorithm_HandleRamLoadEnd(BootAlgorithm *algorithm)
{
    uint32_t packets;
    uint32_t total_words;
    uint32_t loaded_start;
    uint32_t loaded_end;
    uint32_t crc32;
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
                       (total_words == algorithm->ram_load.processed_total_words) &&
                       (algorithm->ram_load.entry_point >= algorithm->ram_load.loaded_start) &&
                       (algorithm->ram_load.entry_point < algorithm->ram_load.loaded_end_exclusive));
    loaded_start = algorithm->ram_load.loaded_start;
    loaded_end = algorithm->ram_load.loaded_end_exclusive;
    crc32 = BootCrc32_Finalize(algorithm->ram_load.crc32);
    if (valid == 0U)
    {
        BootAlgorithm_ResetRamLoad(algorithm);
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_TOTAL_COUNT_MISMATCH,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_STATE, 0UL, total_words);
        return;
    }

    algorithm->ram_load.active = 0U;
    algorithm->ram_load.loaded_start = loaded_start;
    algorithm->ram_load.loaded_end_exclusive = loaded_end;
    algorithm->ram_load.expected_total_words = total_words;
    algorithm->ram_load.processed_total_words = total_words;
    algorithm->ram_load.expected_packet_count = packets;
    algorithm->ram_load.processed_packet_count = packets;
    algorithm->ram_load.crc32 = crc32;
    algorithm->ram_load.image_ready = 1U;
    algorithm->ram_load.crc_checked = 0U;
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

static void BootAlgorithm_HandleRamCheckCrc(BootAlgorithm *algorithm)
{
    uint32_t expected_crc;
    uint32_t expected_words;

    if (algorithm->request.payload_words != 5U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        return;
    }
    if (algorithm->request.payload[4] != 0U)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_FLAGS);
        return;
    }
    if (algorithm->ram_load.image_ready == 0U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_INVALID_STATE,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return;
    }
    expected_crc = BootAlgorithm_JoinU32(algorithm->request.payload[0],
                                         algorithm->request.payload[1]);
    expected_words = BootAlgorithm_JoinU32(algorithm->request.payload[2],
                                           algorithm->request.payload[3]);
    if ((expected_crc != algorithm->ram_load.crc32) ||
        (expected_words != algorithm->ram_load.expected_total_words))
    {
        algorithm->ram_load.crc_checked = 0U;
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_VERIFY_MISMATCH,
                           BOOT_ERR_OP_RAM_LOAD, BOOT_ERR_STAGE_VERIFY,
                           algorithm->ram_load.loaded_start,
                           algorithm->ram_load.expected_total_words);
        return;
    }
    algorithm->ram_load.crc_checked = 1U;
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

#if BOOT_ENABLE_RUN_RAM
static BootAlgorithmAction BootAlgorithm_HandleRunRam(BootAlgorithm *algorithm)
{
    uint32_t entry_point;
    BootRamErrorInfo info = {0U, 0UL, 0UL, 0UL};

    if (algorithm->request.payload_words != 3U)
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                           BOOT_ERR_OP_RUN, BOOT_ERR_STAGE_PAYLOAD, 0UL, 0UL);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    if (algorithm->request.payload[2] != 0U)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_FLAGS);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    if ((algorithm->ram_load.image_ready == 0U) ||
        (algorithm->ram_load.crc_checked == 0U))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_INVALID_STATE,
                           BOOT_ERR_OP_RUN, BOOT_ERR_STAGE_STATE, 0UL, 0UL);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    entry_point = BootAlgorithm_JoinU32(algorithm->request.payload[0],
                                        algorithm->request.payload[1]);
    if (entry_point == 0UL)
    {
        entry_point = algorithm->ram_load.entry_point;
    }
    if ((BootAlgorithm_IsInLoadedRamImage(algorithm, entry_point) == 0U) ||
        (BootRam_CheckAddress(entry_point, 1UL, BOOT_TARGET_RAM_APP, &info) !=
         BOOT_RAM_RESULT_OK))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_RAM_REGION_ERROR,
                           BOOT_ERR_OP_RUN, BOOT_ERR_STAGE_ADDRESS_CHECK,
                           entry_point, 1UL);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    algorithm->pending_entry_point = entry_point;
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
    return BOOT_ALGORITHM_ACTION_RUN_RAM_APP;
}
#endif

static BootAlgorithmAction BootAlgorithm_HandleRun(BootAlgorithm *algorithm)
{
    uint32_t entry_point;
    BootMetadataSummary summary;

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

    BootMetadata_ScanFlashRecords(BOOT_METADATA_SLOT_A_START, &summary);
    if ((summary.metadata_valid == 0U) || (summary.entry_point != entry_point))
    {
        BootAlgorithm_Fail(algorithm, BOOT_STATUS_METADATA_INVALID,
                           BOOT_ERR_OP_RUN, BOOT_ERR_STAGE_STATE,
                           entry_point, 1UL);
        return BOOT_ALGORITHM_ACTION_NONE;
    }
    if ((summary.app_confirmed == 0U) &&
        ((summary.boot_attempt_count == 0U) ||
         (summary.boot_attempt_count > summary.boot_attempt_limit)))
    {
        BootAlgorithm_Fail(algorithm,
                           (summary.boot_attempt_count > summary.boot_attempt_limit) ?
                           BOOT_STATUS_ATTEMPT_LIMIT_REACHED : BOOT_STATUS_INVALID_STATE,
                           BOOT_ERR_OP_RUN, BOOT_ERR_STAGE_STATE,
                           entry_point, 1UL);
        return BOOT_ALGORITHM_ACTION_NONE;
    }

    algorithm->pending_entry_point = entry_point;
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
    return BOOT_ALGORITHM_ACTION_RUN_FLASH_APP;
}

static void BootAlgorithm_HandleGetServiceStatus(BootAlgorithm *algorithm)
{
    uint16_t payload[12];

    if (algorithm->request.payload_words != 0U)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
        return;
    }
    payload[0] = algorithm->service_state.state;
    payload[1] = BOOT_FLASH_SERVICE_ABI_MAJOR;
    payload[2] = BOOT_FLASH_SERVICE_ABI_MINOR;
    payload[3] = 0U;
    payload[4] = 0U;
    BootAlgorithm_SplitU32(algorithm->service_state.capabilities,
                           &payload[5], &payload[6]);
    payload[7] = algorithm->service_state.last_attach_status;
    BootAlgorithm_SplitU32(algorithm->service_state.loaded_crc32,
                           &payload[8], &payload[9]);
    BootAlgorithm_SplitU32(algorithm->service_state.loaded_words,
                           &payload[10], &payload[11]);

    BootProtocol_SendResponse(&algorithm->io,
                              &algorithm->request,
                              BOOT_PKT_RESPONSE,
                              BOOT_STATUS_OK,
                              payload,
                              12U);
}

static void BootAlgorithm_FailServiceAttach(BootAlgorithm *algorithm,
                                            uint16_t status,
                                            uint32_t address,
                                            uint32_t length_words)
{
    if (algorithm->service_active == 0U)
    {
        algorithm->service_state.state = BOOT_SERVICE_STATE_ERROR;
    }
    algorithm->service_state.last_attach_status = status;
    BootAlgorithm_Fail(algorithm, status, BOOT_ERR_OP_RAM_LOAD,
                       BOOT_ERR_STAGE_STATE, address, length_words);
}

static void BootAlgorithm_HandleServiceAttach(BootAlgorithm *algorithm)
{
    uint32_t header_address;
    uint32_t expected_crc32;
    uint32_t expected_words;
    uint16_t status;
    BootFlashServiceHandleCommandFn command_handler;

    if (algorithm->request.payload_words != 7U)
    {
        BootAlgorithm_FailServiceAttach(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                                        0UL, 0UL);
        return;
    }
    if (algorithm->request.payload[6] != 0U)
    {
        BootAlgorithm_FailServiceAttach(algorithm, BOOT_STATUS_BAD_FLAGS, 0UL, 0UL);
        return;
    }

    header_address = BootAlgorithm_JoinU32(algorithm->request.payload[0],
                                           algorithm->request.payload[1]);
    expected_crc32 = BootAlgorithm_JoinU32(algorithm->request.payload[2],
                                           algorithm->request.payload[3]);
    expected_words = BootAlgorithm_JoinU32(algorithm->request.payload[4],
                                           algorithm->request.payload[5]);
    if ((algorithm->ram_load.image_ready == 0U) ||
        (algorithm->ram_load.crc_checked == 0U))
    {
        BootAlgorithm_FailServiceAttach(algorithm, BOOT_STATUS_INVALID_STATE,
                                        header_address, expected_words);
        return;
    }
    if ((expected_crc32 != algorithm->ram_load.crc32) ||
        (expected_words != algorithm->ram_load.expected_total_words))
    {
        BootAlgorithm_FailServiceAttach(algorithm, BOOT_STATUS_VERIFY_MISMATCH,
                                        algorithm->ram_load.loaded_start,
                                        algorithm->ram_load.expected_total_words);
        return;
    }
    if ((header_address != BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS) ||
        (BootAlgorithm_IsRangeInLoadedRamImage(
             algorithm,
             header_address,
             BOOT_FLASH_SERVICE_HEADER_RESERVED_WORDS) == 0U))
    {
        BootAlgorithm_FailServiceAttach(algorithm, BOOT_STATUS_RAM_REGION_ERROR,
                                        header_address,
                                        BOOT_FLASH_SERVICE_HEADER_RESERVED_WORDS);
        return;
    }

    status = BootAlgorithm_ValidateFlashService(&algorithm->device_info,
                                                &command_handler);
    if (status != BOOT_STATUS_OK)
    {
        BootAlgorithm_FailServiceAttach(algorithm, status,
                                        header_address,
                                        BOOT_FLASH_SERVICE_HEADER_WORDS);
        return;
    }

    algorithm->service_command_handler = command_handler;
    algorithm->service_active = 1U;
    algorithm->service_state.state = BOOT_SERVICE_STATE_ATTACHED;
    algorithm->service_state.capabilities = BootAlgorithm_JoinU32(
        BOOT_SERVICE_READ_WORD(BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + 20UL),
        BOOT_SERVICE_READ_WORD(BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + 21UL));
    algorithm->service_state.last_attach_status = BOOT_STATUS_OK;
    algorithm->service_state.loaded_crc32 = algorithm->ram_load.crc32;
    algorithm->service_state.loaded_words = algorithm->ram_load.expected_total_words;
    BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
}

#if BOOT_ENABLE_MEMORY_READ
static void BootAlgorithm_HandleMemoryRead(BootAlgorithm *algorithm)
{
    uint16_t response_capacity = algorithm->device_info.max_payload_words;
    uint16_t max_read_words;
    uint16_t word_count;
    uint16_t flags;
    uint16_t index;
    uint32_t start_address;

    if (algorithm->request.payload_words != 4U)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
        return;
    }
    start_address = BootAlgorithm_JoinU32(algorithm->request.payload[0],
                                          algorithm->request.payload[1]);
    word_count = algorithm->request.payload[2];
    flags = algorithm->request.payload[3];
    if (flags != 0U)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_FLAGS);
        return;
    }
    if (response_capacity > BOOT_PROTOCOL_MAX_PAYLOAD_WORDS)
    {
        response_capacity = BOOT_PROTOCOL_MAX_PAYLOAD_WORDS;
    }
    max_read_words = (response_capacity > 3U) ? (uint16_t)(response_capacity - 3U) : 0U;
    if ((word_count == 0U) || (word_count > max_read_words))
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_WORD_COUNT);
        return;
    }

    algorithm->request.payload[0] = (uint16_t)(start_address & 0xFFFFUL);
    algorithm->request.payload[1] = (uint16_t)(start_address >> 16U);
    algorithm->request.payload[2] = word_count;
    for (index = 0U; index < word_count; index++)
    {
        algorithm->request.payload[3U + index] =
            BOOT_MEMORY_READ_WORD(start_address + (uint32_t)index);
    }
    BootProtocol_SendResponse(&algorithm->io,
                              &algorithm->request,
                              BOOT_PKT_RESPONSE,
                              BOOT_STATUS_OK,
                              algorithm->request.payload,
                              (uint16_t)(3U + word_count));
}
#endif

static void BootAlgorithm_HandleGetMetadataSummary(BootAlgorithm *algorithm)
{
    BootMetadataSummary summary;
    uint16_t payload[BOOT_METADATA_SUMMARY_WORDS];

    if (algorithm->request.payload_words != 0U)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
        return;
    }

    BootMetadata_ScanFlashRecords(BOOT_METADATA_SLOT_A_START, &summary);
    BootMetadataSummary_ToPayload(&summary, payload);
    BootProtocol_SendResponse(&algorithm->io,
                              &algorithm->request,
                              BOOT_PKT_RESPONSE,
                              BOOT_STATUS_OK,
                              payload,
                              BOOT_METADATA_SUMMARY_WORDS);
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
    BootAlgorithm_ResetServiceState(algorithm);
    algorithm->pending_entry_point = 0UL;
    return 1U;
}

uint16_t BootAlgorithm_RestoreFlashService(BootAlgorithm *algorithm)
{
    BootFlashServiceHandleCommandFn command_handler;
    uint16_t status;

    if (algorithm == NULL)
    {
        return BOOT_STATUS_INVALID_STATE;
    }
    status = BootAlgorithm_ValidateFlashService(&algorithm->device_info,
                                                &command_handler);
    if (status != BOOT_STATUS_OK)
    {
        BootAlgorithm_InvalidateFlashService(algorithm);
        return status;
    }
    algorithm->service_command_handler = command_handler;
    algorithm->service_active = 1U;
    algorithm->service_state.state = BOOT_SERVICE_STATE_ATTACHED;
    algorithm->service_state.capabilities = BootAlgorithm_JoinU32(
        BOOT_SERVICE_READ_WORD(BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + 20UL),
        BOOT_SERVICE_READ_WORD(BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS + 21UL));
    algorithm->service_state.last_attach_status = BOOT_STATUS_OK;
    return BOOT_STATUS_OK;
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

        case BOOT_CMD_GET_SERVICE_STATUS:
            BootAlgorithm_HandleGetServiceStatus(algorithm);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_SERVICE_ATTACH:
            BootAlgorithm_HandleServiceAttach(algorithm);
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
        case BOOT_CMD_RAM_CHECK_CRC:
            BootAlgorithm_HandleRamCheckCrc(algorithm);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_RUN_RAM:
#if BOOT_ENABLE_RUN_RAM
            return BootAlgorithm_HandleRunRam(algorithm);
#else
            BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_UNSUPPORTED_FEATURE);
            return BOOT_ALGORITHM_ACTION_NONE;
#endif
#if BOOT_ENABLE_MEMORY_READ
        case BOOT_CMD_MEMORY_READ:
            BootAlgorithm_HandleMemoryRead(algorithm);
            return BOOT_ALGORITHM_ACTION_NONE;
#endif
        case BOOT_CMD_GET_METADATA_SUMMARY:
            BootAlgorithm_HandleGetMetadataSummary(algorithm);
            return BOOT_ALGORITHM_ACTION_NONE;
        case BOOT_CMD_RUN:
            return BootAlgorithm_HandleRun(algorithm);
        case BOOT_CMD_RESET:
#if BOOT_ENABLE_RESET_COMMAND
            if (algorithm->request.payload_words != 0U)
            {
                BootAlgorithm_Fail(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                                   BOOT_ERR_OP_RESET, BOOT_ERR_STAGE_PAYLOAD,
                                   0UL, 0UL);
                return BOOT_ALGORITHM_ACTION_NONE;
            }
            BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_OK);
            return BOOT_ALGORITHM_ACTION_RESET_DEVICE;
#else
            BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_UNSUPPORTED_FEATURE);
            return BOOT_ALGORITHM_ACTION_NONE;
#endif
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
