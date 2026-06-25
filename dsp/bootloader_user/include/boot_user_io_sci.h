#ifndef BOOT_USER_IO_SCI_H
#define BOOT_USER_IO_SCI_H


#include "boot_io.h"
#include "F2837xD_device.h"


static inline void BootSci_Flush(void)
{
    while(!SciaRegs.SCICTL2.bit.TXEMPTY) { }
}

void BootSCI_Init();

BootIoConnectResult BootSci_CreateIoOps(void *ctx, BootIoOps *ops);

void BootSci_ConnectStartup(void);

BootIoConnectResult BootSci_ConnectFinish(void);

void BootSci_ConnectShutdown(void);

#endif
