#include "boot_io.h"

/*
 * USER ACTION REQUIRED:
 * - bind ctx to the product SCI driver state;
 * - perform the ASCII 'A' autobaud exchange inside connect_master;
 * - enforce timeout_ms locally without creating a protocol timeout status;
 * - convert two wire bytes (low byte first) to/from one protocol word.
 *
 * Do not add protocol framing or ACK/NAK handling here.
 */
#error "Implement the product SCI BootIoOps port before compiling this file"

static BootIoConnectResult BootUser_ConnectMaster(void *ctx, uint32_t timeout_ms)
{
    (void)ctx;
    (void)timeout_ms;
    return BOOT_IO_CONNECT_FAILED;
}

static uint16_t BootUser_GetWord(void *ctx)
{
    (void)ctx;
    return 0U;
}

static void BootUser_SendWord(void *ctx, uint16_t word)
{
    (void)ctx;
    (void)word;
}

uint16_t BootUser_CreateIoOps(void *ctx, BootIoOps *ops)
{
    if (ops == 0)
    {
        return 0U;
    }
    ops->ctx = ctx;
    ops->connect_master = BootUser_ConnectMaster;
    ops->get_word = BootUser_GetWord;
    ops->send_word = BootUser_SendWord;
    return 1U;
}
