#ifndef BOOT_USER_ACTION_H
#define BOOT_USER_ACTION_H

#include <stdint.h>

#include "boot_algorithm.h"

#ifdef __cplusplus
extern "C" {
#endif

uint16_t BootUser_HandleAlgorithmAction(BootAlgorithm *algorithm,
                                        BootAlgorithmAction action);

void BootUser_JumpToFlashApp(uint32_t entry_point);
void BootUser_ResetDevicePlaceholder(void);

#ifdef __cplusplus
}
#endif

#endif
