#include "F28x_Project.h"
#include "boot_user_io.h"
#include "boot_algorithm.h"
#include "boot_user_action.h"
#include "boot_user_auto_boot.h"
#include "boot_user_device_info.h"
#include "boot_user_config.h"
#include "boot_metadata.h"

void main(void)
{
    static BootAlgorithm algorithm;
    BootIoOps io;
    BootDeviceInfo device_info;
    BootUserIoCtx user_ctx;
    BootAlgorithmAction action;
    BootMetadataSummary metadata_summary;
    uint16_t confirmed_bootable;
    uint16_t connect_result;

    //
    // Initialize System Control:
    // PLL, WatchDog, enable Peripheral Clocks
    // This example function is found in the F2837xD_SysCtrl.c file.
    //
    InitSysCtrl();

    //
    // Initialize GPIO:
    // This example function is found in the F2837xD_Gpio.c file and
    // illustrates how to set the GPIO to it's default state.
    //
    InitGpio();

    //
    // Clear all interrupts and initialize PIE vector table:
    // Disable CPU interrupts
    //
    DINT;

    //
    // Initialize the PIE control registers to their default state.
    // The default state is all PIE interrupts disabled and flags
    // are cleared.
    // This function is found in the F2837xD_PieCtrl.c file.
    //
    // InitPieCtrl();

    //
    // Disable CPU interrupts and clear all CPU interrupt flags:
    //
    IER = 0x0000;
    IFR = 0x0000;

    //
    // Initialize the PIE vector table with pointers to the shell Interrupt
    // Service Routines (ISR).
    // This will populate the entire table, even if the interrupt
    // is not used in this example.  This is useful for debug purposes.
    // The shell ISR routines are found in F2837xD_DefaultISR.c.
    // This function is found in F2837xD_PieVect.c.
    //
    // InitPieVectTable();

    //
    // Step 6. User specific code
    //
    BootUser_InitIoOps();
    if (BootUser_CreateDeviceInfo(&device_info) == 0U)
    {
        return;
    }
    BootMetadata_ScanFlashRecords(BOOT_METADATA_SLOT_A_START, &metadata_summary);
    confirmed_bootable = BootUser_IsConfirmedBootable(&metadata_summary);
    connect_result = BootUser_CreateIoOpsTimeout(NULL, &io, &user_ctx,
#if BOOT_USER_AUTO_BOOT_ENABLE
                                                 BOOT_USER_GUI_WAIT_WINDOW_MS,
                                                 (confirmed_bootable != 0U) ? 0U : 1U
#else
                                                 BOOT_USER_TIMEOUT_MS,
                                                 1U
#endif
                                                 );
    if (connect_result == BOOT_IO_CONNECT_TIMEOUT)
    {
#if BOOT_USER_AUTO_BOOT_ENABLE
        if (confirmed_bootable != 0U)
        {
            BootUser_JumpToFlashApp(metadata_summary.entry_point);
        }
#endif
        return;
    }
    if ((connect_result != BOOT_IO_CONNECT_OK) ||
        (BootAlgorithm_Init(&algorithm, &io, &device_info) == 0U))
    {
        return;
    }

    action = BootAlgorithm_Run(&algorithm);
    (void)BootUser_HandleAlgorithmAction(&algorithm, action);
}
