#include "F28x_Project.h"
#include "boot_user_io.h"
#include "boot_user_config.h"
#include "boot_user_io_sci.h"


void BootUser_InitIoOps(void)
{
    #if (BOOT_USER_IO_SCI_ENABLE)
    BootSCI_Init();
    BootSci_Flush();
    #endif
}

void BootUser_ShutdownUnuseIoOps(uint16_t io_id)
{
    #if (BOOT_USER_IO_SCI_ENABLE)
    if (io_id != BOOT_USER_IO_ID_SCI)
    {
        BootSci_ConnectShutdown();
    }
    #endif
}

uint16_t BootUser_CreateIoOps(void *ctx, BootIoOps *ops, BootUserIoCtx *user_ctx)
{
    uint32_t timeTicks = 0;
    BootUserIoId io_id = BOOT_USER_IO_ID_NONE;
    BootIoConnectResult connectResult;

    #if (BOOT_USER_IO_SCI_ENABLE)
    BootSci_ConnectStartup();
    #endif

    do
    {
        #if (BOOT_USER_IO_SCI_ENABLE)
        connectResult = BootSci_ConnectFinish();
        if (connectResult == BOOT_IO_CONNECT_OK)
        {
            io_id = BOOT_USER_IO_ID_SCI;
            connectResult = BootSci_CreateIoOps(ctx, ops);
            break;  // Connection successful, exit the loop
        }
        #endif

        DELAY_US(10U);  // Wait 10us before retrying
        timeTicks++;  // Increment timeTicks by 1 (10us) 
    }while(timeTicks < (BOOT_USER_TIMEOUT_MS * 100UL));

    // If no successful connection was made, set io_id to NONE
    if (connectResult != BOOT_IO_CONNECT_OK)
    {
        io_id = BOOT_USER_IO_ID_NONE;
    }
    BootUser_ShutdownUnuseIoOps(io_id);
    user_ctx->io_id = io_id;

    if (timeTicks >= (BOOT_USER_TIMEOUT_MS * 100UL))
    {
        return BOOT_IO_CONNECT_TIMEOUT;  // Timeout occurred
    }

    return connectResult;  // Connection successful
}
