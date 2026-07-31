#include "boot_user_watchdog.h"

#include "F28x_Project.h"
#include "boot_user_action.h"

#define BOOT_USER_WATCHDOG_ENABLE_VALUE   0x002FU
#define BOOT_USER_WATCHDOG_DISABLE_VALUE  0x006FU
#define BOOT_USER_WATCHDOG_INTERRUPT_MODE 0x0002U

static BootUserWatchdogContext *g_boot_user_watchdog_context;

__interrupt void BootUser_WatchdogIsr(void);

static void BootUser_WatchdogServiceHardware(void)
{
    EALLOW;
    WdRegs.WDKEY.bit.WDKEY = 0x0055U;
    WdRegs.WDKEY.bit.WDKEY = 0x00AAU;
    EDIS;
}

static void BootUser_WatchdogDisable(BootUserWatchdogContext *context)
{
    EALLOW;
    WdRegs.WDCR.all = BOOT_USER_WATCHDOG_DISABLE_VALUE;
    EDIS;
    context->watchdog_running = 0U;
}

static void BootUser_WatchdogEnable(BootUserWatchdogContext *context)
{
    EALLOW;
    WdRegs.WDCR.all = BOOT_USER_WATCHDOG_ENABLE_VALUE;
    EDIS;
    context->watchdog_running = 1U;
}

void BootUser_WatchdogContextInit(BootUserWatchdogContext *context,
                                  uint16_t confirmed_bootable,
                                  uint32_t app_entry_point)
{
    context->confirmed_bootable = (confirmed_bootable != 0U) ? 1U : 0U;
    context->watchdog_running = 0U;
    context->guard_watchdog_was_running = 0U;
    context->guard_interrupt_state = 0U;
    context->app_entry_point = app_entry_point;
    g_boot_user_watchdog_context = context;
}

void BootUser_WatchdogStart(BootUserWatchdogContext *context)
{
    DINT;
    EALLOW;
    PieVectTable.WAKE_INT = &BootUser_WatchdogIsr;
    WdRegs.SCSR.all = BOOT_USER_WATCHDOG_INTERRUPT_MODE;
    WdRegs.WDWCR.all = 0U;
    EDIS;

    PieCtrlRegs.PIEACK.all = PIEACK_GROUP1;
    PieCtrlRegs.PIECTRL.bit.ENPIE = 1U;
    PieCtrlRegs.PIEIER1.bit.INTx8 = 1U;
    IER |= M_INT1;
    BootUser_WatchdogServiceHardware();
    BootUser_WatchdogEnable(context);
    EINT;
}

void BootUser_WatchdogStop(void)
{
    if ((g_boot_user_watchdog_context != 0) &&
        (g_boot_user_watchdog_context->watchdog_running != 0U))
    {
        BootUser_WatchdogDisable(g_boot_user_watchdog_context);
    }
}

void BootUser_WatchdogOnValidRequestFrame(void *context)
{
    (void)context;
    BootUser_WatchdogServiceHardware();
}

uint16_t BootUser_WatchdogServiceGuardEnter(void *context)
{
    BootUserWatchdogContext *watchdog = (BootUserWatchdogContext *)context;
    uint16_t interrupt_state = __disable_interrupts();

    __restore_interrupts(interrupt_state);
    watchdog->guard_interrupt_state = interrupt_state;
    watchdog->guard_watchdog_was_running = watchdog->watchdog_running;
    if (watchdog->guard_watchdog_was_running != 0U)
    {
        BootUser_WatchdogDisable(watchdog);
    }
    DINT;
    return interrupt_state;
}

void BootUser_WatchdogServiceGuardExit(void *context, uint16_t token)
{
    BootUserWatchdogContext *watchdog = (BootUserWatchdogContext *)context;

    if (watchdog->guard_watchdog_was_running != 0U)
    {
        BootUser_WatchdogEnable(watchdog);
    }
    __restore_interrupts(token);
}

__interrupt void BootUser_WatchdogIsr(void)
{
    BootUserWatchdogContext *watchdog = g_boot_user_watchdog_context;

    if (watchdog->confirmed_bootable != 0U)
    {
        BootUser_WatchdogDisable(watchdog);
        BootUser_EmergencyJumpToFlashApp(watchdog->app_entry_point);
    }

    EALLOW;
    WdRegs.SCSR.all = 0U;
    EDIS;
    for (;;)
    {
    }
}
