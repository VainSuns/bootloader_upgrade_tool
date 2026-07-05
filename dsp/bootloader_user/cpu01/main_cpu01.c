#include "F28x_Project.h"
#include "boot_user_io.h"
#include "boot_algorithm.h"
#include "boot_user_action.h"
#include "boot_user_device_info.h"
#include "boot_user_config.h"

void main(void)
{
    static BootAlgorithm algorithm;
    BootIoOps io;
    BootDeviceInfo device_info;
    BootUserIoCtx user_ctx;
    BootAlgorithmAction action;

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
    if ((BootUser_CreateIoOps(NULL, &io, &user_ctx) != BOOT_IO_CONNECT_OK) ||
        (BootUser_CreateDeviceInfo(&device_info) == 0U) ||
        (BootAlgorithm_Init(&algorithm, &io, &device_info) == 0U))
    {
        return;
    }

    action = BootAlgorithm_Run(&algorithm);
    (void)BootUser_HandleAlgorithmAction(&algorithm, action);
}
