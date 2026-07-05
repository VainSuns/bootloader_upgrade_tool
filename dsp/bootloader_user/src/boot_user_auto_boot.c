#include "boot_user_auto_boot.h"

#include <stddef.h>

#include "boot_protocol.h"
#include "boot_service_abi.h"
#include "boot_user_action.h"
#include "boot_user_app_layout.h"
#include "boot_user_config.h"

static void BootUser_SplitU32(uint16_t *words, uint32_t value)
{
    words[0] = (uint16_t)(value & 0xFFFFUL);
    words[1] = (uint16_t)(value >> 16U);
}

static uint16_t BootUser_IsValidAutoBootEntry(uint32_t entry_point)
{
    return (uint16_t)((entry_point >= BOOT_USER_APP_START) &&
                      (entry_point < BOOT_USER_APP_END_EXCLUSIVE) &&
                      ((entry_point % 8UL) == 0UL));
}

BootUserAutoBootDecision BootUser_PreviewAutoBootDecision(
    const BootMetadataSummary *summary,
    uint16_t service_ready,
    uint16_t boot_attempt_write_ok)
{
    if ((summary == NULL) || (summary->state == BOOT_METADATA_SCAN_EMPTY))
    {
        return BOOT_USER_DECISION_STAY_NO_IMAGE;
    }
    if ((summary->metadata_valid == 0U) || (summary->has_image_valid == 0U))
    {
        return BOOT_USER_DECISION_STAY_METADATA_INVALID;
    }
    if (BootUser_IsValidAutoBootEntry(summary->entry_point) == 0U)
    {
        return BOOT_USER_DECISION_STAY_BAD_ENTRY;
    }
    if ((summary->boot_attempt_count == 0U) && (summary->app_confirmed == 0U))
    {
        if (service_ready == 0U)
        {
            return BOOT_USER_DECISION_STAY_SERVICE_NOT_READY;
        }
        return (boot_attempt_write_ok != 0U) ?
               BOOT_USER_DECISION_RUN_FIRST_TRIAL :
               BOOT_USER_DECISION_STAY_BOOT_ATTEMPT_WRITE_FAILED;
    }
    if ((summary->boot_attempt_count > 0U) && (summary->app_confirmed != 0U))
    {
        return BOOT_USER_DECISION_RUN_CONFIRMED_APP;
    }
    if (summary->app_confirmed != 0U)
    {
        return BOOT_USER_DECISION_STAY_METADATA_INVALID;
    }
    return BOOT_USER_DECISION_STAY_WAIT_APP_CONFIRM;
}

static uint16_t BootUser_AppendBootAttempt(BootAlgorithm *algorithm,
                                           const BootMetadataSummary *summary)
{
    BootProtocolFrame request = {0};
    uint16_t response_payload[BOOT_PROTOCOL_MAX_PAYLOAD_WORDS];
    uint16_t response_payload_words = 0U;
    BootErrorDetail error;

    if ((algorithm == NULL) ||
        (summary == NULL) ||
        (algorithm->service_active == 0U) ||
        (algorithm->service_api == NULL) ||
        (algorithm->service_api->handle_command == NULL))
    {
        return 0U;
    }

    request.protocol_ver = BOOT_PROTOCOL_VERSION;
    request.packet_type = BOOT_PKT_REQUEST;
    request.command = BOOT_CMD_METADATA_APPEND_RECORD;
    request.payload_words = 16U;
    request.payload[0] = BOOT_METADATA_RECORD_BOOT_ATTEMPT;
    request.payload[1] = BOOT_SLOT_A;
    BootUser_SplitU32(&request.payload[2], summary->entry_point);
    BootUser_SplitU32(&request.payload[4], summary->image_size_words);
    BootUser_SplitU32(&request.payload[6], summary->image_crc32);
    BootErrorDetail_Clear(&error);

    return (uint16_t)(algorithm->service_api->handle_command(&request,
                                                             response_payload,
                                                             &response_payload_words,
                                                             &error) ==
                      BOOT_STATUS_OK);
}

BootUserAutoBootDecision BootUser_TryAutoBoot(BootAlgorithm *algorithm)
{
    BootMetadataSummary summary;
    uint16_t service_ready = 0U;
    uint16_t write_ok = 0U;
    BootUserAutoBootDecision decision;

    BootMetadata_ScanFlashRecords(BOOT_METADATA_SLOT_A_START, &summary);
    decision = BootUser_PreviewAutoBootDecision(&summary, 0U, 0U);
    if ((decision == BOOT_USER_DECISION_STAY_METADATA_INVALID) ||
        (decision == BOOT_USER_DECISION_STAY_NO_IMAGE) ||
        (decision == BOOT_USER_DECISION_STAY_BAD_ENTRY) ||
        (decision == BOOT_USER_DECISION_STAY_WAIT_APP_CONFIRM))
    {
        return decision;
    }
    if (decision == BOOT_USER_DECISION_RUN_CONFIRMED_APP)
    {
        BootUser_JumpToFlashApp(summary.entry_point);
        return decision;
    }

    service_ready = BootAlgorithm_TryAttachExistingService(
        algorithm,
        BOOT_USER_SERVICE_DESCRIPTOR_ADDRESS);
    if (service_ready != 0U)
    {
        write_ok = BootUser_AppendBootAttempt(algorithm, &summary);
    }
    decision = BootUser_PreviewAutoBootDecision(&summary, service_ready, write_ok);
    if (decision == BOOT_USER_DECISION_RUN_FIRST_TRIAL)
    {
        BootUser_JumpToFlashApp(summary.entry_point);
    }
    return decision;
}
