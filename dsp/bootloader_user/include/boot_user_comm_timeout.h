#ifndef BOOT_USER_COMM_TIMEOUT_H
#define BOOT_USER_COMM_TIMEOUT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void BootUser_CommTimeoutStart(void);
void BootUser_CommTimeoutStop(void);
void BootUser_CommTimeoutOnValidRequestFrame(void *context);
uint16_t BootUser_CommTimeoutServiceGuardEnter(void *context);
void BootUser_CommTimeoutServiceGuardExit(void *context,
                                          uint16_t interrupt_state);

#ifdef __cplusplus
}
#endif

#endif
