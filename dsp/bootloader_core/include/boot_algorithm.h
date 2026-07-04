#ifndef BOOT_ALGORITHM_H
#define BOOT_ALGORITHM_H

#include <stdint.h>

#include "boot_device_info.h"
#include "boot_io.h"
#include "boot_protocol.h"
#include "boot_service_abi.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum
{
    BOOT_ALGORITHM_ACTION_NONE = 0,
    BOOT_ALGORITHM_ACTION_RUN_FLASH_APP = 1,
    BOOT_ALGORITHM_ACTION_RESET_DEVICE = 2,
    BOOT_ALGORITHM_ACTION_RUN_RAM_APP = 3
} BootAlgorithmAction;

typedef struct
{
    uint16_t active;
    uint16_t target;
    uint32_t expected_packet_count;
    uint32_t processed_packet_count;
    uint32_t expected_total_words;
    uint32_t processed_total_words;
    uint32_t expected_block_index;
    uint32_t entry_point;
    uint32_t loaded_start;
    uint32_t loaded_end_exclusive;
    uint32_t crc32;
    uint16_t image_ready;
    uint16_t crc_checked;
} BootTransferSession;

typedef struct
{
    BootIoOps io;
    BootDeviceInfo device_info;
    BootErrorDetail last_error;
    BootProtocolFrame request;
    BootTransferSession ram_load;
    BootCoreServices core_services;
    const BootServiceApi *service_api;
    uint16_t service_active;
    uint16_t service_image_ready;
    uint32_t pending_entry_point;
} BootAlgorithm;

uint16_t BootAlgorithm_Init(BootAlgorithm *algorithm,
                            const BootIoOps *io,
                            const BootDeviceInfo *device_info);

BootAlgorithmAction BootAlgorithm_ProcessOne(BootAlgorithm *algorithm);
BootAlgorithmAction BootAlgorithm_Run(BootAlgorithm *algorithm);
uint16_t BootAlgorithm_AttachService(BootAlgorithm *algorithm,
                                     const BootServiceApi *service_api);
uint32_t BootAlgorithm_GetPendingEntryPoint(const BootAlgorithm *algorithm);

#ifdef __cplusplus
}
#endif

#endif
