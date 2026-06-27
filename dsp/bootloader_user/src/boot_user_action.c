#include "boot_user_action.h"
#include "F28x_Project.h"

uint16_t BootUser_HandleAlgorithmAction(BootAlgorithm *algorithm,
                                        BootAlgorithmAction action)
{
    switch (action)
    {
        case BOOT_ALGORITHM_ACTION_RUN_FLASH_APP:
            BootUser_JumpToFlashApp(BootAlgorithm_GetPendingEntryPoint(algorithm));
            return 1U;

        case BOOT_ALGORITHM_ACTION_RESET_DEVICE:
            BootUser_ResetDevicePlaceholder();
            return 1U;

        case BOOT_ALGORITHM_ACTION_NONE:
        default:
            return 0U;
    }
}

void BootUser_JumpToFlashApp(uint32_t entry_point)
{
    /*
     * Minimal cleanup before handing control to the application.
     *
     * Keep this user-layer only.
     * Do not move this logic into bootloader_core.
     */

    DINT;

    IER = 0x0000U;
    IFR = 0x0000U;


    asm(" LB 0x082000");
}

void BootUser_ResetDevicePlaceholder(void)
{
    // Do nothing for now.
    for(;;)
    {
        // Wait for watchdog timer to reset the device.
    }
}
