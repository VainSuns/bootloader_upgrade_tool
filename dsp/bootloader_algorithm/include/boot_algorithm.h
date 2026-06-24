#ifndef BOOT_ALGORITHM_H
#define BOOT_ALGORITHM_H

#include <stdint.h>

#include "boot_device_info.h"
#include "boot_io.h"
#include "boot_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct
{
    BootIoOps io;
    BootDeviceInfo device_info;
    BootErrorDetail last_error;
    BootProtocolFrame request;
} BootAlgorithm;

uint16_t BootAlgorithm_Init(BootAlgorithm *algorithm,
                            const BootIoOps *io,
                            const BootDeviceInfo *device_info);

void BootAlgorithm_ProcessOne(BootAlgorithm *algorithm);
void BootAlgorithm_Run(BootAlgorithm *algorithm);

#ifdef __cplusplus
}
#endif

#endif

