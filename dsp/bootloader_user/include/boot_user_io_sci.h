#ifndef BOOT_USER_IO_SCI_H
#define BOOT_USER_IO_SCI_H


#include "boot_io.h"
#include "F2837xD_device.h"


static inline void BootSci_Flush(void)
{
    /*
     * FIFO mode: wait for queued bytes to leave the TX FIFO, then wait for the
     * transmitter to become empty. RUN uses this before branching to the app.
     */
    while (SciaRegs.SCIFFTX.bit.TXFFST != 0U)
    {
    }
    while (SciaRegs.SCICTL2.bit.TXEMPTY == 0U)
    {
    }
}

void BootSCI_Init();

BootIoConnectResult BootSci_CreateIoOps(void *ctx, BootIoOps *ops);

void BootSci_ConnectStartup(void);

BootIoConnectResult BootSci_ConnectFinish(void);

void BootSci_ConnectShutdown(void);

#endif
