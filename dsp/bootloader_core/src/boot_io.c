#include "boot_io.h"

#include <stddef.h>

uint16_t BootIo_IsValid(const BootIoOps *ops)
{
    if ((ops == NULL) ||
        (ops->get_byte == NULL) ||
        (ops->get_word == NULL) || (ops->send_word == NULL))
    {
        return 0U;
    }
    return 1U;
}

uint16_t BootIo_GetByte(const BootIoOps *ops)
{
    return (uint16_t)(ops->get_byte(ops->ctx) & 0x00FFU);
}

uint16_t BootIo_GetWord(const BootIoOps *ops)
{
    return ops->get_word(ops->ctx);
}

void BootIo_SendWord(const BootIoOps *ops, uint16_t word)
{
    ops->send_word(ops->ctx, word);
}
