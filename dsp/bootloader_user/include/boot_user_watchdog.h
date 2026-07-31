#ifndef BOOT_USER_WATCHDOG_H
#define BOOT_USER_WATCHDOG_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct
{
    volatile uint16_t confirmed_bootable;
    volatile uint16_t watchdog_running;
    volatile uint16_t guard_watchdog_was_running;
    volatile uint16_t guard_interrupt_state;
    volatile uint32_t app_entry_point;
} BootUserWatchdogContext;

void BootUser_WatchdogContextInit(BootUserWatchdogContext *context,
                                  uint16_t confirmed_bootable,
                                  uint32_t app_entry_point);
void BootUser_WatchdogStart(BootUserWatchdogContext *context);
void BootUser_WatchdogStop(void);
void BootUser_WatchdogOnValidRequestFrame(void *context);
uint16_t BootUser_WatchdogServiceGuardEnter(void *context);
void BootUser_WatchdogServiceGuardExit(void *context, uint16_t token);

#ifdef __cplusplus
}
#endif

#endif
