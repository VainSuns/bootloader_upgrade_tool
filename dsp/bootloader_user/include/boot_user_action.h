#ifndef BOOT_USER_ACTION_H
#define BOOT_USER_ACTION_H

#include <stdint.h>

#include "boot_algorithm.h"
#include "boot_user_feature_config.h"

#ifdef __cplusplus
extern "C" {
#endif

uint16_t BootUser_HandleAlgorithmAction(BootAlgorithm *algorithm,
                                        BootAlgorithmAction action);

void BootUser_JumpToFlashApp(uint32_t entry_point);
#if BOOT_ENABLE_RUN_RAM
void BootUser_JumpToRamApp(uint32_t entry_point);
#endif
#if BOOT_ENABLE_RESET_COMMAND
void BootUser_ResetDevicePlaceholder(void);
#endif

#ifdef __cplusplus
}
#endif

#endif
