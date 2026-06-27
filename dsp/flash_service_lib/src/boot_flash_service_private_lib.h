#ifndef BOOT_FLASH_SERVICE_PRIVATE_LIB_H
#define BOOT_FLASH_SERVICE_PRIVATE_LIB_H

#include "boot_flash_port.h"
#include "boot_service_abi.h"

typedef enum
{
    BOOT_FLASH_SERVICE_SESSION_NONE = 0,
    BOOT_FLASH_SERVICE_SESSION_PROGRAM = 1,
    BOOT_FLASH_SERVICE_SESSION_VERIFY = 2
} BootFlashServiceSessionOperation;

typedef struct
{
    BootFlashServiceSessionOperation operation;
    uint16_t target;
    uint32_t expected_packet_count;
    uint32_t processed_packet_count;
    uint32_t expected_total_words;
    uint32_t processed_total_words;
    uint32_t expected_block_index;
    uint32_t entry_point;
} BootFlashServiceSession;

typedef struct
{
    BootCoreServices core;
    BootFlashServiceSession session;
    uint16_t initialized;
    uint16_t flash_initialized;
    uint16_t flash_modified;
    uint16_t verify_succeeded;
} BootFlashServiceState;

void BootFlashService_ResetSession(BootFlashServiceSession *session);
uint16_t BootFlashService_MapResult(BootFlashResult result,
                                    uint16_t failed_status,
                                    uint16_t bad_address_status);
void BootFlashService_SetError(BootFlashServiceState *state,
                               BootErrorDetail *error,
                               uint16_t operation,
                               uint16_t stage,
                               uint32_t address,
                               uint32_t length_words,
                               uint16_t extra0,
                               uint16_t extra1);
void BootFlashService_SetFlashError(BootFlashServiceState *state,
                                    BootErrorDetail *error,
                                    uint16_t operation,
                                    uint16_t stage,
                                    BootFlashResult result,
                                    const BootFlashErrorInfo *info);

#endif
