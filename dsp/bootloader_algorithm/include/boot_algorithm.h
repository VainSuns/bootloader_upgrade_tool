#ifndef BOOT_ALGORITHM_H
#define BOOT_ALGORITHM_H

#include <stdint.h>

#include "boot_device_info.h"
#include "boot_flash_port.h"
#include "boot_io.h"
#include "boot_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum
{
    BOOT_ALGORITHM_ACTION_NONE = 0,
    BOOT_ALGORITHM_ACTION_RUN_FLASH_APP = 1,
    BOOT_ALGORITHM_ACTION_RESET_DEVICE = 2
} BootAlgorithmAction;

typedef enum
{
    BOOT_SESSION_NONE = 0,
    BOOT_SESSION_PROGRAM = 1,
    BOOT_SESSION_VERIFY = 2
} BootSessionOperation;

typedef struct
{
    BootSessionOperation operation;
    uint16_t target;
    uint32_t expected_packet_count;
    uint32_t processed_packet_count;
    uint32_t expected_total_words;
    uint32_t processed_total_words;
    uint32_t expected_block_index;
    uint32_t entry_point;
} BootTransferSession;

typedef struct
{
    BootIoOps io;
    BootDeviceInfo device_info;
    BootErrorDetail last_error;
    BootProtocolFrame request;
    BootTransferSession session;
    uint16_t flash_initialized;
    uint16_t flash_modified;
    uint16_t verify_succeeded;
} BootAlgorithm;

uint16_t BootAlgorithm_Init(BootAlgorithm *algorithm,
                            const BootIoOps *io,
                            const BootDeviceInfo *device_info);

BootAlgorithmAction BootAlgorithm_ProcessOne(BootAlgorithm *algorithm);
BootAlgorithmAction BootAlgorithm_Run(BootAlgorithm *algorithm);

#ifdef __cplusplus
}
#endif

#endif
