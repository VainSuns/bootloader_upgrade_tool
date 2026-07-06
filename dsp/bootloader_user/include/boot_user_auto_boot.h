#ifndef BOOT_USER_AUTO_BOOT_H
#define BOOT_USER_AUTO_BOOT_H

#include <stdint.h>

#include "boot_algorithm.h"
#include "boot_metadata.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum
{
    BOOT_USER_DECISION_STAY_NO_IMAGE = 0,
    BOOT_USER_DECISION_STAY_METADATA_INVALID = 1,
    BOOT_USER_DECISION_STAY_BAD_ENTRY = 2,
    BOOT_USER_DECISION_STAY_FIRST_TRIAL_REQUIRES_PC_RUN = 3,
    BOOT_USER_DECISION_STAY_WAIT_APP_CONFIRM = 4,
    BOOT_USER_DECISION_RUN_CONFIRMED_APP = 5
} BootUserAutoBootDecision;

BootUserAutoBootDecision BootUser_PreviewAutoBootDecision(
    const BootMetadataSummary *summary);

uint16_t BootUser_IsConfirmedBootable(const BootMetadataSummary *summary);

#ifdef __cplusplus
}
#endif

#endif
