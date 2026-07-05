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
    BOOT_USER_DECISION_STAY_SERVICE_NOT_READY = 3,
    BOOT_USER_DECISION_STAY_BOOT_ATTEMPT_WRITE_FAILED = 4,
    BOOT_USER_DECISION_STAY_WAIT_APP_CONFIRM = 5,
    BOOT_USER_DECISION_RUN_FIRST_TRIAL = 6,
    BOOT_USER_DECISION_RUN_CONFIRMED_APP = 7
} BootUserAutoBootDecision;

BootUserAutoBootDecision BootUser_PreviewAutoBootDecision(
    const BootMetadataSummary *summary,
    uint16_t service_ready,
    uint16_t boot_attempt_write_ok);

BootUserAutoBootDecision BootUser_TryAutoBoot(BootAlgorithm *algorithm);

#ifdef __cplusplus
}
#endif

#endif
