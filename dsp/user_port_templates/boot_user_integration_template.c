#include "boot_algorithm.h"

/* Implemented by the reviewed user-port files. */
extern uint16_t BootUser_CreateIoOps(void *ctx, BootIoOps *ops);
extern uint16_t BootUser_CreateDeviceInfo(BootDeviceInfo *info);

/*
 * USER ACTION REQUIRED:
 * Call this only after the product-owned clock, watchdog, pinmux, SCI, RAM,
 * Flash wait-state, and security policy initialization is complete. Decide
 * whether a failed/timed-out connection returns to the boot policy or retries.
 */
#error "Integrate the algorithm into the product boot policy before compiling this file"

BootAlgorithmAction BootUser_RunProtocolLoop(void *io_context)
{
    static BootAlgorithm algorithm;
    BootIoOps io;
    BootDeviceInfo device_info;

    if ((BootUser_CreateIoOps(io_context, &io) == 0U) ||
        (BootUser_CreateDeviceInfo(&device_info) == 0U) ||
        (BootAlgorithm_Init(&algorithm, &io, &device_info) == 0U))
    {
        return BOOT_ALGORITHM_ACTION_NONE;
    }

    /* Handle the returned action in product-owned jump/reset code. */
    return BootAlgorithm_Run(&algorithm);
}
