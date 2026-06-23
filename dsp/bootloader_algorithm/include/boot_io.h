#ifndef BOOT_IO_H
#define BOOT_IO_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum
{
    BOOT_IO_CONNECT_OK = 0,
    BOOT_IO_CONNECT_TIMEOUT = 1,
    BOOT_IO_CONNECT_FAILED = 2
} BootIoConnectResult;

typedef struct
{
    void *ctx;
    BootIoConnectResult (*connect_master)(void *ctx, uint32_t timeout_ms);
    uint16_t (*get_word)(void *ctx);
    void (*send_word)(void *ctx, uint16_t word);
} BootIoOps;

BootIoConnectResult BootIo_ConnectMaster(const BootIoOps *ops, uint32_t timeout_ms);
uint16_t BootIo_GetWord(const BootIoOps *ops);
void BootIo_SendWord(const BootIoOps *ops, uint16_t word);
uint16_t BootIo_IsValid(const BootIoOps *ops);

#ifdef __cplusplus
}
#endif

#endif

