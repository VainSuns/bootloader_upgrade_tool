#ifndef BOOT_USER_IO_H
#define BOOT_USER_IO_H


#include "boot_io.h"

typedef enum
{
    BOOT_USER_IO_ID_NONE = 0,
    BOOT_USER_IO_ID_SCI = 1
} BootUserIoId;


typedef struct
{
    BootUserIoId io_id;
} BootUserIoCtx;


void BootUser_InitIoOps(void);

uint16_t BootUser_CreateIoOps(void *ctx, BootIoOps *ops, BootUserIoCtx *user_ctx);


#endif
