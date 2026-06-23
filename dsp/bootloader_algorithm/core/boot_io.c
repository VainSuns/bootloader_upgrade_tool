#include "boot_io.h"

#include <stddef.h>

uint16_t BootIo_IsValid(const BootIoOps *ops)
{
    if ((ops == NULL) || (ops->connect_master == NULL) ||
        (ops->get_word == NULL) || (ops->send_word == NULL))
    {
        return 0U;
    }
    return 1U;
}

BootIoConnectResult BootIo_ConnectMaster(const BootIoOps *ops, uint32_t timeout_ms)
{
    if (BootIo_IsValid(ops) == 0U)
    {
        return BOOT_IO_CONNECT_FAILED;
    }
    return ops->connect_master(ops->ctx, timeout_ms);
}

uint16_t BootIo_GetWord(const BootIoOps *ops)
{
    return ops->get_word(ops->ctx);
}

void BootIo_SendWord(const BootIoOps *ops, uint16_t word)
{
    ops->send_word(ops->ctx, word);
}

