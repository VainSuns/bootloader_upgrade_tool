#include "boot_algorithm.h"

/* Implemented by the reviewed user-port files. */
extern BootIoOps BootUser_CreateIoOps(void *ctx);
extern BootDeviceInfo BootUser_CreateDeviceInfo(void);

/*
 * USER ACTION REQUIRED:
 * Call this only after the product-owned clock, watchdog, pinmux, SCI, RAM,
 * Flash wait-state, and security policy initialization is complete. Decide
 * whether a failed/timed-out connection returns to the boot policy or retries.
 */
#error "Integrate the algorithm into the product boot policy before compiling this file"

void BootUser_RunProtocolLoop(void *io_context)
{
    static BootAlgorithm algorithm;
    BootIoOps io = BootUser_CreateIoOps(io_context);
    BootDeviceInfo device_info = BootUser_CreateDeviceInfo();

    if (BootAlgorithm_Init(&algorithm, &io, &device_info) == 0U)
    {
        return;
    }

    /* Connection timeout is local policy and is never returned as DSP status. */
    BootAlgorithm_Run(&algorithm, 5000UL);
}
