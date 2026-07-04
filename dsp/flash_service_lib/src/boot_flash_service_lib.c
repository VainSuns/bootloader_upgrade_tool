#include "boot_flash_service_lib.h"

#include <stddef.h>

#include "boot_crc32.h"
#include "boot_metadata.h"
#include "boot_flash_service_private_lib.h"

static BootFlashServiceState g_service;

static uint32_t BootFlashService_JoinU32(uint16_t low, uint16_t high)
{
    return ((uint32_t)high << 16U) | (uint32_t)low;
}

static uint16_t BootFlashService_EnsureFlash(uint16_t operation,
                                             uint16_t failed_status,
                                             BootErrorDetail *error)
{
    BootFlashErrorInfo info = {BOOT_FLASH_OP_NONE, 0UL, 0UL, 0L, 0UL, 0UL};
    BootFlashResult result;
    uint16_t status;

    if (g_service.flash_initialized != 0U)
    {
        return BOOT_STATUS_OK;
    }

    result = BootFlash_Init(&info);
    status = BootFlashService_MapResult(result,
                                        failed_status,
                                        BOOT_STATUS_BAD_ADDRESS);
    if (status != BOOT_STATUS_OK)
    {
        BootFlashService_SetFlashError(&g_service,
                                       error,
                                       operation,
                                       BOOT_ERR_STAGE_API_CALL,
                                       result,
                                       &info);
        return status;
    }
    g_service.flash_initialized = 1U;
    return BOOT_STATUS_OK;
}

static uint16_t BootFlashService_Fail(BootErrorDetail *error,
                                      uint16_t status,
                                      uint16_t operation,
                                      uint16_t stage,
                                      uint32_t address,
                                      uint32_t length_words)
{
    BootFlashService_SetError(&g_service,
                              error,
                              operation,
                              stage,
                              address,
                              length_words,
                              0U,
                              0U);
    return status;
}

static uint16_t BootFlashService_HandleErase(const BootProtocolFrame *request,
                                             BootErrorDetail *error)
{
    BootFlashErrorInfo info = {BOOT_FLASH_OP_NONE, 0UL, 0UL, 0L, 0UL, 0UL};
    BootFlashResult result;
    uint32_t sector_mask;
    uint16_t status;

    if (request->payload_words != 3U)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                                     BOOT_ERR_OP_ERASE, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }
    if (request->payload[2] != 0U)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_FLAGS,
                                     BOOT_ERR_OP_ERASE, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }

    sector_mask = BootFlashService_JoinU32(request->payload[0], request->payload[1]);
    if (sector_mask == 0UL)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_ADDRESS,
                                     BOOT_ERR_OP_ERASE,
                                     BOOT_ERR_STAGE_ADDRESS_CHECK,
                                     0UL, 0UL);
    }

    status = BootFlashService_EnsureFlash(BOOT_ERR_OP_ERASE,
                                          BOOT_STATUS_ERASE_FAILED,
                                          error);
    if (status != BOOT_STATUS_OK)
    {
        return status;
    }

    info.operation = BOOT_FLASH_OP_ERASE;
    info.extra = sector_mask;
    result = BootFlash_EraseBySectorMask(sector_mask, &info);
    status = BootFlashService_MapResult(result,
                                        BOOT_STATUS_ERASE_FAILED,
                                        BOOT_STATUS_BAD_ADDRESS);
    if (status != BOOT_STATUS_OK)
    {
        BootFlashService_SetFlashError(&g_service,
                                       error,
                                       BOOT_ERR_OP_ERASE,
                                       BOOT_ERR_STAGE_API_CALL,
                                       result,
                                       &info);
        return status;
    }

    BootFlashService_ResetSession(&g_service.session);
    g_service.flash_modified = 1U;
    g_service.verify_succeeded = 0U;
    return BOOT_STATUS_OK;
}

static uint16_t BootFlashService_HandleBegin(const BootProtocolFrame *request,
                                             BootFlashServiceSessionOperation session_operation,
                                             uint16_t error_operation,
                                             uint16_t failed_status,
                                             BootErrorDetail *error)
{
    uint32_t total_words;
    uint16_t status;

    if (g_service.session.operation != BOOT_FLASH_SERVICE_SESSION_NONE)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BUSY, error_operation,
                                     BOOT_ERR_STAGE_STATE, 0UL, 0UL);
    }
    if (request->payload_words != 9U)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                                     error_operation, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }
    if (request->payload[0] != BOOT_TARGET_FLASH_APP)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_TARGET_MISMATCH,
                                     error_operation, BOOT_ERR_STAGE_STATE,
                                     0UL, 0UL);
    }

    total_words = BootFlashService_JoinU32(request->payload[2],
                                           request->payload[3]);
    if ((request->payload[1] == 0U) || (total_words == 0UL))
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_WORD_COUNT,
                                     error_operation, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, total_words);
    }

    status = BootFlashService_EnsureFlash(error_operation, failed_status, error);
    if (status != BOOT_STATUS_OK)
    {
        return status;
    }

    g_service.session.operation = session_operation;
    g_service.session.target = BOOT_TARGET_FLASH_APP;
    g_service.session.expected_packet_count = request->payload[1];
    g_service.session.processed_packet_count = 0UL;
    g_service.session.expected_total_words = total_words;
    g_service.session.processed_total_words = 0UL;
    g_service.session.expected_block_index = 0UL;
    g_service.session.entry_point = BootFlashService_JoinU32(request->payload[4],
                                                             request->payload[5]);
    return BOOT_STATUS_OK;
}

static uint16_t BootFlashService_HandleData(const BootProtocolFrame *request,
                                            BootFlashServiceSessionOperation session_operation,
                                            uint16_t error_operation,
                                            BootFlashOperation flash_operation,
                                            uint16_t failed_status,
                                            BootErrorDetail *error)
{
    BootFlashErrorInfo info = {BOOT_FLASH_OP_NONE, 0UL, 0UL, 0L, 0UL, 0UL};
    BootFlashResult result;
    uint32_t address;
    uint32_t block_index;
    uint16_t data_words;
    uint16_t status;
    uint16_t stage;

    if (g_service.session.operation == BOOT_FLASH_SERVICE_SESSION_NONE)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_MISSING_BEGIN,
                                     error_operation, BOOT_ERR_STAGE_STATE,
                                     0UL, 0UL);
    }
    if (g_service.session.operation != session_operation)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_INVALID_STATE,
                                     error_operation, BOOT_ERR_STAGE_STATE,
                                     0UL, 0UL);
    }
    if (request->payload_words < 5U)
    {
        BootFlashService_ResetSession(&g_service.session);
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                                     error_operation, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }

    address = BootFlashService_JoinU32(request->payload[0], request->payload[1]);
    data_words = request->payload[2];
    block_index = BootFlashService_JoinU32(request->payload[3], request->payload[4]);
    if (request->payload_words != (uint16_t)(5U + data_words))
    {
        BootFlashService_ResetSession(&g_service.session);
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                                     error_operation, BOOT_ERR_STAGE_PAYLOAD,
                                     address, data_words);
    }
    if ((data_words == 0U) || ((data_words % 8U) != 0U) ||
        (data_words > g_service.core.device_info->max_data_words))
    {
        BootFlashService_ResetSession(&g_service.session);
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_WORD_COUNT,
                                     error_operation, BOOT_ERR_STAGE_PAYLOAD,
                                     address, data_words);
    }
    if (block_index != g_service.session.expected_block_index)
    {
        BootFlashService_SetError(&g_service, error, error_operation,
                                  BOOT_ERR_STAGE_STATE, address, data_words,
                                  (uint16_t)(g_service.session.expected_block_index & 0xFFFFUL),
                                  (uint16_t)(g_service.session.expected_block_index >> 16U));
        BootFlashService_ResetSession(&g_service.session);
        return BOOT_STATUS_BLOCK_INDEX_ERROR;
    }
    if ((g_service.session.processed_packet_count >=
         g_service.session.expected_packet_count) ||
        ((uint32_t)data_words >
         g_service.session.expected_total_words -
         g_service.session.processed_total_words))
    {
        BootFlashService_ResetSession(&g_service.session);
        return BootFlashService_Fail(error, BOOT_STATUS_TOTAL_COUNT_MISMATCH,
                                     error_operation, BOOT_ERR_STAGE_STATE,
                                     address, data_words);
    }

    info.operation = flash_operation;
    info.address = address;
    info.length_words = data_words;
    result = BootFlash_CheckAddress(address, data_words, flash_operation, &info);
    status = BootFlashService_MapResult(result,
                                        failed_status,
                                        BOOT_STATUS_ADDRESS_OUT_OF_RANGE);
    if (status != BOOT_STATUS_OK)
    {
        BootFlashService_SetFlashError(&g_service, error, error_operation,
                                       BOOT_ERR_STAGE_ADDRESS_CHECK,
                                       result, &info);
        BootFlashService_ResetSession(&g_service.session);
        return status;
    }

    if (session_operation == BOOT_FLASH_SERVICE_SESSION_PROGRAM)
    {
        result = BootFlash_ProgramBlock(address, &request->payload[5],
                                        data_words, &info);
        stage = BOOT_ERR_STAGE_API_CALL;
    }
    else
    {
        result = BootFlash_VerifyBlock(address, &request->payload[5],
                                       data_words, &info);
        stage = BOOT_ERR_STAGE_VERIFY;
    }
    status = BootFlashService_MapResult(result,
                                        failed_status,
                                        BOOT_STATUS_ADDRESS_OUT_OF_RANGE);
    if (status != BOOT_STATUS_OK)
    {
        BootFlashService_SetFlashError(&g_service, error, error_operation,
                                       stage, result, &info);
        BootFlashService_ResetSession(&g_service.session);
        return status;
    }

    ++g_service.session.processed_packet_count;
    g_service.session.processed_total_words += data_words;
    ++g_service.session.expected_block_index;
    if (session_operation == BOOT_FLASH_SERVICE_SESSION_PROGRAM)
    {
        g_service.flash_modified = 1U;
        g_service.verify_succeeded = 0U;
    }
    return BOOT_STATUS_OK;
}

static uint16_t BootFlashService_HandleEnd(const BootProtocolFrame *request,
                                           BootFlashServiceSessionOperation session_operation,
                                           uint16_t error_operation,
                                           BootErrorDetail *error)
{
    uint32_t packet_count;
    uint32_t total_words;
    uint16_t valid;

    if (g_service.session.operation == BOOT_FLASH_SERVICE_SESSION_NONE)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_MISSING_BEGIN,
                                     error_operation, BOOT_ERR_STAGE_STATE,
                                     0UL, 0UL);
    }
    if (g_service.session.operation != session_operation)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_UNEXPECTED_END,
                                     error_operation, BOOT_ERR_STAGE_STATE,
                                     0UL, 0UL);
    }
    if (request->payload_words != 6U)
    {
        BootFlashService_ResetSession(&g_service.session);
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                                     error_operation, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }

    packet_count = BootFlashService_JoinU32(request->payload[0],
                                            request->payload[1]);
    total_words = BootFlashService_JoinU32(request->payload[2],
                                           request->payload[3]);
    valid = (uint16_t)((packet_count == g_service.session.expected_packet_count) &&
                       (packet_count == g_service.session.processed_packet_count) &&
                       (total_words == g_service.session.expected_total_words) &&
                       (total_words == g_service.session.processed_total_words));
    BootFlashService_ResetSession(&g_service.session);
    if (valid == 0U)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_TOTAL_COUNT_MISMATCH,
                                     error_operation, BOOT_ERR_STAGE_STATE,
                                     0UL, total_words);
    }
    if (session_operation == BOOT_FLASH_SERVICE_SESSION_VERIFY)
    {
        g_service.verify_succeeded = 1U;
    }
    return BOOT_STATUS_OK;
}

static uint16_t BootFlashService_MetadataRequestValid(const BootProtocolFrame *request,
                                                      uint32_t *entry_point,
                                                      uint32_t *image_size_words,
                                                      uint32_t *image_crc32,
                                                      uint32_t *app_version_build,
                                                      uint32_t *app_end,
                                                      BootErrorDetail *error)
{
    if (request->payload_words != 16U)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }
    if (request->payload[0] != BOOT_METADATA_RECORD_IMAGE_VALID)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_UNSUPPORTED_FEATURE,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }
    if (request->payload[1] != BOOT_SLOT_A)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_UNSUPPORTED_FEATURE,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }
    if (request->payload[15] != 0U)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_FLAGS,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }

    *entry_point = BootFlashService_JoinU32(request->payload[2], request->payload[3]);
    *image_size_words = BootFlashService_JoinU32(request->payload[4], request->payload[5]);
    *image_crc32 = BootFlashService_JoinU32(request->payload[6], request->payload[7]);
    *app_version_build = BootFlashService_JoinU32(request->payload[11], request->payload[12]);
    *app_end = BootFlashService_JoinU32(request->payload[13], request->payload[14]);

    if (*image_size_words == 0UL)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_WORD_COUNT,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_PAYLOAD,
                                     *entry_point, 0UL);
    }
    if ((*entry_point < BOOT_METADATA_SLOT_A_APP_START) ||
        (*entry_point >= BOOT_METADATA_SLOT_A_APP_END) ||
        ((*entry_point % 8UL) != 0UL) ||
        (*app_end <= BOOT_METADATA_SLOT_A_APP_START) ||
        (*app_end > BOOT_METADATA_SLOT_A_APP_END))
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_ADDRESS,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_ADDRESS_CHECK,
                                     *entry_point, *image_size_words);
    }

    return BOOT_STATUS_OK;
}

static uint16_t BootFlashService_ProgramMetadataRecord(uint32_t record_address,
                                                       const uint16_t record[BOOT_METADATA_RECORD_WORDS],
                                                       BootErrorDetail *error)
{
    BootFlashErrorInfo info = {BOOT_FLASH_OP_PROGRAM, 0UL, 0UL, 0L, 0UL, 0UL};
    BootFlashResult result;
    uint16_t status;

    status = BootFlashService_EnsureFlash(BOOT_ERR_OP_PROGRAM,
                                          BOOT_STATUS_METADATA_WRITE_FAILED,
                                          error);
    if (status != BOOT_STATUS_OK)
    {
        return status;
    }

    info.address = record_address;
    info.length_words = BOOT_METADATA_RECORD_WORDS;
    result = BootFlash_ProgramMetadataRecord(record_address, record,
                                             (uint16_t)BOOT_METADATA_RECORD_WORDS,
                                             &info);
    if (result != BOOT_FLASH_RESULT_OK)
    {
        BootFlashService_SetFlashError(&g_service,
                                       error,
                                       BOOT_ERR_OP_PROGRAM,
                                       BOOT_ERR_STAGE_API_CALL,
                                       result,
                                       &info);
        return BOOT_STATUS_METADATA_WRITE_FAILED;
    }
    return BOOT_STATUS_OK;
}

static uint16_t BootFlashService_MetadataRecordAddress(const BootMetadataSummary *summary,
                                                       uint32_t *record_address,
                                                       BootErrorDetail *error)
{
    if (summary->next_record_index == BOOT_METADATA_INVALID_INDEX)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_METADATA_FULL,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_STATE,
                                     0UL, 0UL);
    }

    *record_address = BOOT_METADATA_SLOT_A_START +
                      ((uint32_t)summary->next_record_index * BOOT_METADATA_RECORD_WORDS);
    if (((*record_address % BOOT_METADATA_RECORD_WORDS) != 0UL) ||
        (*record_address < BOOT_METADATA_SLOT_A_START) ||
        ((*record_address + BOOT_METADATA_RECORD_WORDS) > BOOT_METADATA_SLOT_A_APP_START))
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_ADDRESS,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_ADDRESS_CHECK,
                                     *record_address, BOOT_METADATA_RECORD_WORDS);
    }
    return BOOT_STATUS_OK;
}

static uint16_t BootFlashService_HandleBootAttemptAppend(const BootProtocolFrame *request,
                                                         BootErrorDetail *error)
{
    BootMetadataSummary summary;
    BootMetadataSummary written_summary;
    uint16_t record[BOOT_METADATA_RECORD_WORDS];
    uint32_t entry_point;
    uint32_t image_size_words;
    uint32_t image_crc32;
    uint32_t record_address;
    uint16_t index;
    uint16_t status;

    if (request->payload_words != 16U)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }
    if (request->payload[1] != BOOT_SLOT_A)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_UNSUPPORTED_FEATURE,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }
    if (request->payload[15] != 0U)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_BAD_FLAGS,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_PAYLOAD,
                                     0UL, 0UL);
    }
    for (index = 8U; index <= 14U; index++)
    {
        if (request->payload[index] != 0U)
        {
            return BootFlashService_Fail(error, BOOT_STATUS_BAD_PAYLOAD_LENGTH,
                                         BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_PAYLOAD,
                                         0UL, 0UL);
        }
    }

    BootMetadata_ScanFlashRecords(BOOT_METADATA_SLOT_A_START, &summary);
    if ((summary.metadata_valid == 0U) || (summary.state == BOOT_METADATA_SCAN_DUPLICATE_SEQUENCE))
    {
        return BootFlashService_Fail(error, BOOT_STATUS_METADATA_INVALID,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_STATE,
                                     0UL, 0UL);
    }
    if (summary.app_confirmed != 0U)
    {
        return BOOT_STATUS_OK;
    }
    if (summary.boot_attempt_count >= summary.boot_attempt_limit)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_ATTEMPT_LIMIT_REACHED,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_STATE,
                                     summary.entry_point, summary.image_size_words);
    }

    entry_point = BootFlashService_JoinU32(request->payload[2], request->payload[3]);
    image_size_words = BootFlashService_JoinU32(request->payload[4], request->payload[5]);
    image_crc32 = BootFlashService_JoinU32(request->payload[6], request->payload[7]);
    if ((entry_point != summary.entry_point) ||
        (image_size_words != summary.image_size_words) ||
        (image_crc32 != summary.image_crc32))
    {
        return BootFlashService_Fail(error, BOOT_STATUS_METADATA_INVALID,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_STATE,
                                     entry_point, image_size_words);
    }

    status = BootFlashService_MetadataRecordAddress(&summary, &record_address, error);
    if (status != BOOT_STATUS_OK)
    {
        return status;
    }

    BootMetadata_BuildBootAttemptRecord(record,
                                        summary.latest_sequence + 1UL,
                                        &summary,
                                        (uint16_t)(summary.boot_attempt_count + 1U));
    status = BootFlashService_ProgramMetadataRecord(record_address, record, error);
    if (status != BOOT_STATUS_OK)
    {
        return status;
    }

    BootMetadata_ScanFlashRecords(BOOT_METADATA_SLOT_A_START, &written_summary);
    if ((written_summary.metadata_valid == 0U) ||
        (written_summary.boot_attempt_count != (uint16_t)(summary.boot_attempt_count + 1U)))
    {
        return BootFlashService_Fail(error, BOOT_STATUS_METADATA_WRITE_FAILED,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_VERIFY,
                                     record_address, BOOT_METADATA_RECORD_WORDS);
    }
    return BOOT_STATUS_OK;
}

static uint16_t BootFlashService_HandleMetadataAppendRecord(const BootProtocolFrame *request,
                                                            BootErrorDetail *error)
{
    BootMetadataSummary summary;
    BootMetadataSummary written_summary;
    uint16_t record[BOOT_METADATA_RECORD_WORDS];
    uint32_t entry_point;
    uint32_t image_size_words;
    uint32_t image_crc32;
    uint32_t app_version_build;
    uint32_t app_end;
    uint32_t sequence;
    uint32_t record_address;
    uint16_t status;

    if ((request != NULL) && (request->payload_words == 16U) &&
        (request->payload[0] == BOOT_METADATA_RECORD_BOOT_ATTEMPT))
    {
        return BootFlashService_HandleBootAttemptAppend(request, error);
    }

    status = BootFlashService_MetadataRequestValid(request,
                                                   &entry_point,
                                                   &image_size_words,
                                                   &image_crc32,
                                                   &app_version_build,
                                                   &app_end,
                                                   error);
    if (status != BOOT_STATUS_OK)
    {
        return status;
    }
    if (g_service.verify_succeeded == 0U)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_INVALID_STATE,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_STATE,
                                     entry_point, image_size_words);
    }

    BootMetadata_ScanFlashRecords(BOOT_METADATA_SLOT_A_START, &summary);
    if (summary.state == BOOT_METADATA_SCAN_DUPLICATE_SEQUENCE)
    {
        return BootFlashService_Fail(error, BOOT_STATUS_METADATA_INVALID,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_STATE,
                                     0UL, 0UL);
    }
    sequence = (summary.valid_record_count == 0U) ? 1UL : (summary.latest_sequence + 1UL);
    status = BootFlashService_MetadataRecordAddress(&summary, &record_address, error);
    if (status != BOOT_STATUS_OK)
    {
        return status;
    }

    BootMetadata_BuildImageValidRecord(record,
                                       sequence,
                                       entry_point,
                                       image_size_words,
                                       image_crc32,
                                       request->payload[8],
                                       request->payload[9],
                                       request->payload[10],
                                       app_version_build,
                                       app_end,
                                       g_service.core.device_info->device_id,
                                       g_service.core.device_info->cpu_id);

    status = BootFlashService_ProgramMetadataRecord(record_address, record, error);
    if (status != BOOT_STATUS_OK)
    {
        return status;
    }

    BootMetadata_ScanFlashRecords(BOOT_METADATA_SLOT_A_START, &written_summary);
    if ((written_summary.metadata_valid == 0U) ||
        (written_summary.image_valid_sequence != sequence) ||
        (written_summary.entry_point != entry_point) ||
        (written_summary.image_crc32 != image_crc32))
    {
        return BootFlashService_Fail(error, BOOT_STATUS_METADATA_WRITE_FAILED,
                                     BOOT_ERR_OP_PROGRAM, BOOT_ERR_STAGE_VERIFY,
                                     record_address, BOOT_METADATA_RECORD_WORDS);
    }

    g_service.verify_succeeded = 0U;
    return BOOT_STATUS_OK;
}

static uint16_t BootFlashService_Init(const BootCoreServices *core_services)
{
    if ((core_services == NULL) ||
        (core_services->abi_major != BOOT_SERVICE_ABI_MAJOR) ||
        (core_services->size != (uint16_t)sizeof(BootCoreServices)) ||
        (core_services->device_info == NULL))
    {
        return 0U;
    }
    g_service.core = *core_services;
    BootFlashService_ResetSession(&g_service.session);
    g_service.initialized = 1U;
    g_service.flash_initialized = 0U;
    g_service.flash_modified = 0U;
    g_service.verify_succeeded = 0U;
    return 1U;
}

static uint16_t BootFlashService_HandleCommand(const BootProtocolFrame *request,
                                               uint16_t *response_payload,
                                               uint16_t *response_payload_words,
                                               BootErrorDetail *error)
{
    (void)response_payload;
    if ((request == NULL) || (response_payload_words == NULL) || (error == NULL))
    {
        return BOOT_STATUS_INVALID_STATE;
    }
    if ((g_service.initialized == 0U) ||
        (g_service.core.device_info == NULL))
    {
        return BOOT_STATUS_INVALID_STATE;
    }
    *response_payload_words = 0U;
    BootErrorDetail_Clear(error);

    switch (request->command)
    {
        case BOOT_CMD_ERASE:
            return BootFlashService_HandleErase(request, error);
        case BOOT_CMD_PROGRAM_BEGIN:
            return BootFlashService_HandleBegin(request,
                                                BOOT_FLASH_SERVICE_SESSION_PROGRAM,
                                                BOOT_ERR_OP_PROGRAM,
                                                BOOT_STATUS_PROGRAM_FAILED,
                                                error);
        case BOOT_CMD_PROGRAM_DATA:
            return BootFlashService_HandleData(request,
                                               BOOT_FLASH_SERVICE_SESSION_PROGRAM,
                                               BOOT_ERR_OP_PROGRAM,
                                               BOOT_FLASH_OP_PROGRAM,
                                               BOOT_STATUS_PROGRAM_FAILED,
                                               error);
        case BOOT_CMD_PROGRAM_END:
            return BootFlashService_HandleEnd(request,
                                              BOOT_FLASH_SERVICE_SESSION_PROGRAM,
                                              BOOT_ERR_OP_PROGRAM,
                                              error);
        case BOOT_CMD_VERIFY_BEGIN:
            return BootFlashService_HandleBegin(request,
                                                BOOT_FLASH_SERVICE_SESSION_VERIFY,
                                                BOOT_ERR_OP_VERIFY,
                                                BOOT_STATUS_VERIFY_FAILED,
                                                error);
        case BOOT_CMD_VERIFY_DATA:
            return BootFlashService_HandleData(request,
                                               BOOT_FLASH_SERVICE_SESSION_VERIFY,
                                               BOOT_ERR_OP_VERIFY,
                                               BOOT_FLASH_OP_VERIFY,
                                               BOOT_STATUS_VERIFY_FAILED,
                                               error);
        case BOOT_CMD_VERIFY_END:
            return BootFlashService_HandleEnd(request,
                                              BOOT_FLASH_SERVICE_SESSION_VERIFY,
                                              BOOT_ERR_OP_VERIFY,
                                              error);
        case BOOT_CMD_METADATA_APPEND_RECORD:
            return BootFlashService_HandleMetadataAppendRecord(request, error);
        default:
            return BOOT_STATUS_UNSUPPORTED_COMMAND;
    }
}

static uint16_t BootFlashService_Deinit(void)
{
    BootFlashService_ResetSession(&g_service.session);
    g_service.initialized = 0U;
    g_service.flash_initialized = 0U;
    return 1U;
}

/*
 * These symbols must be retained in the user-built RAM service image. Their
 * final addresses are read from the linker map and supplied to the PC patcher.
 */
const BootServiceApi g_boot_flash_service_api = {
    BOOT_SERVICE_API_MAGIC,
    BOOT_SERVICE_ABI_MAJOR,
    BOOT_SERVICE_ABI_MINOR,
    (uint16_t)sizeof(BootServiceApi),
    BootFlashService_Init,
    BootFlashService_HandleCommand,
    BootFlashService_Deinit
};

uint16_t g_boot_flash_service_descriptor[BOOT_SERVICE_DESCRIPTOR_WORDS];
uint16_t g_boot_flash_service_crc_patch[2];

const BootServiceApi *BootFlashServiceLib_GetApi(void)
{
    return &g_boot_flash_service_api;
}

void BootFlashServiceLib_GetPatchSymbols(const BootServiceApi **api,
                                         uint16_t **descriptor,
                                         uint16_t **crc_patch)
{
    if (api != NULL)
    {
        *api = &g_boot_flash_service_api;
    }
    if (descriptor != NULL)
    {
        *descriptor = g_boot_flash_service_descriptor;
    }
    if (crc_patch != NULL)
    {
        *crc_patch = g_boot_flash_service_crc_patch;
    }
}

static void BootFlashService_SplitU32(uint16_t *words, uint32_t value)
{
    words[0] = (uint16_t)(value & 0xFFFFUL);
    words[1] = (uint16_t)(value >> 16U);
}

void BootFlashServiceLib_BuildDescriptor(uint16_t *descriptor,
                                         uint32_t api_table_address,
                                         uint32_t image_start,
                                         uint32_t image_end_exclusive,
                                         uint32_t image_crc32)
{
    uint16_t index;

    if (descriptor == NULL)
    {
        return;
    }
    for (index = 0U; index < BOOT_SERVICE_DESCRIPTOR_WORDS; index++)
    {
        descriptor[index] = 0U;
    }
    BootFlashService_SplitU32(&descriptor[0], BOOT_SERVICE_DESCRIPTOR_MAGIC);
    descriptor[2] = BOOT_SERVICE_DESCRIPTOR_VERSION;
    descriptor[3] = BOOT_SERVICE_DESCRIPTOR_WORDS;
    descriptor[4] = BOOT_SERVICE_ABI_MAJOR;
    descriptor[5] = BOOT_SERVICE_ABI_MINOR;
    descriptor[6] = 0U;
    descriptor[7] = 1U;
    BootFlashService_SplitU32(&descriptor[8], api_table_address);
    BootFlashService_SplitU32(&descriptor[10], image_start);
    BootFlashService_SplitU32(&descriptor[12], image_end_exclusive);
    BootFlashService_SplitU32(&descriptor[14], image_crc32);
    BootFlashService_SplitU32(&descriptor[16], BOOT_SERVICE_REQUIRED_CAPABILITIES);
    BootFlashService_SplitU32(&descriptor[18],
                              BootCrc32_CalcWords(descriptor, 18UL));
}
