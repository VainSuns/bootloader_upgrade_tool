#include "boot_user_auto_boot.h"

#include <stddef.h>

#include "boot_user_app_layout.h"

static uint16_t BootUser_IsValidAutoBootEntry(uint32_t entry_point)
{
    return (uint16_t)((entry_point >= BOOT_USER_APP_START) &&
                      (entry_point < BOOT_USER_APP_END_EXCLUSIVE) &&
                      ((entry_point % 8UL) == 0UL));
}

BootUserAutoBootDecision BootUser_PreviewAutoBootDecision(
    const BootMetadataSummary *summary)
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
    if (summary->boot_attempt_count == 0U)
    {
        return BOOT_USER_DECISION_STAY_FIRST_TRIAL_REQUIRES_PC_RUN;
    }
    if (summary->app_confirmed == 0U)
    {
        return BOOT_USER_DECISION_STAY_WAIT_APP_CONFIRM;
    }
    return BOOT_USER_DECISION_RUN_CONFIRMED_APP;
}

uint16_t BootUser_IsConfirmedBootable(const BootMetadataSummary *summary)
{
    return (uint16_t)(BootUser_PreviewAutoBootDecision(summary) ==
                      BOOT_USER_DECISION_RUN_CONFIRMED_APP);
}
