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

typedef uint16_t (*BootIoGetByteFn)(void *ctx);
typedef uint16_t (*BootIoGetWordFn)(void *ctx);
typedef void (*BootIoSendWordFn)(void *ctx, uint16_t word);

typedef struct
{
    void *ctx;
    BootIoGetByteFn get_byte;
    BootIoGetWordFn get_word;
    BootIoSendWordFn send_word;
} BootIoOps;

uint16_t BootIo_GetByte(const BootIoOps *ops);
uint16_t BootIo_GetWord(const BootIoOps *ops);
void BootIo_SendWord(const BootIoOps *ops, uint16_t word);
uint16_t BootIo_IsValid(const BootIoOps *ops);

#ifdef __cplusplus
}
#endif

#endif
