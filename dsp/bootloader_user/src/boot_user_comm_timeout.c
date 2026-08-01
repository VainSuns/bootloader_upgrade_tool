// Copyright (C) 2013-2024 Texas Instruments Incorporated
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions
// are met:
//
// * Redistributions of source code must retain the above copyright
//   notice, this list of conditions and the following disclaimer.
// * Redistributions in binary form must reproduce the above copyright
//   notice, this list of conditions and the following disclaimer in the
//   documentation and/or other materials provided with the distribution.
// * Neither the name of Texas Instruments Incorporated nor the names of
//   its contributors may be used to endorse or promote products derived
//   from this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
// "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
// LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
// A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
// OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
// SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
// LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
// DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
// THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
// (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
// OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
// SPDX-License-Identifier: BSD-3-Clause

/*
 * Project-adapted CPU Timer 2 setup and watchdog reset sequence for the
 * TMS320F28377D CPU1 Flash-resident bootloader. Derived from TI F2837xD
 * device-support examples; this is not an unmodified TI source file.
 */

#include "boot_user_comm_timeout.h"

#include "F28x_Project.h"
#include "boot_user_config.h"

#define BOOT_USER_COMM_TIMEOUT_CYCLES \
    ((BOOT_USER_CPU_SYSCLK_HZ * 1ULL * BOOT_USER_COMM_TIMEOUT_MS) / 1000ULL)

/*
 * Synchronize consecutive TMS320F28377D system-control register writes.
 * This matches TI F2837xD SYSCTL_REGWRITE_DELAY; 69 is for the frozen
 * 200 MHz SYSCLK and default 10 MHz INTOSC1 configuration.
 */
#define BOOT_USER_SYSCTRL_REGWRITE_DELAY \
    asm(" RPT #69 || NOP")

#if BOOT_USER_COMM_TIMEOUT_CYCLES == 0ULL
#error "BOOT_USER_COMM_TIMEOUT_MS produces a zero CPU Timer 2 period"
#endif

#if BOOT_USER_COMM_TIMEOUT_CYCLES > 0xFFFFFFFFULL
#error "BOOT_USER_COMM_TIMEOUT_MS exceeds the 32-bit CPU Timer 2 range"
#endif

__interrupt void BootUser_CommTimeoutIsr(void);

static void BootUser_CommTimeoutReload(void)
{
    CpuTimer2Regs.TCR.bit.TRB = 1U;
    CpuTimer2Regs.TCR.bit.TIF = 1U;
    IFR &= (uint16_t)(~M_INT14);
}

static void BootUser_ForceDeviceResetNow(void)
{
    ReleaseFlashPump();

    EALLOW;
    WdRegs.SCSR.all = 0U;
    WdRegs.WDCR.all = 0x0028U;
    BOOT_USER_SYSCTRL_REGWRITE_DELAY;
    WdRegs.WDCR.all = 0x0000U;
    BOOT_USER_SYSCTRL_REGWRITE_DELAY;
    EDIS;
}

void BootUser_CommTimeoutStart(void)
{
    uint16_t interrupt_state = __disable_interrupts();

    EALLOW;
    CpuSysRegs.TMR2CLKCTL.bit.TMR2CLKSRCSEL = 0U;
    BOOT_USER_SYSCTRL_REGWRITE_DELAY;
    CpuSysRegs.TMR2CLKCTL.bit.TMR2CLKPRESCALE = 0U;
    EDIS;
    BOOT_USER_SYSCTRL_REGWRITE_DELAY;

    CpuTimer2Regs.TCR.bit.TSS = 1U;
    CpuTimer2Regs.PRD.all = (uint32_t)BOOT_USER_COMM_TIMEOUT_CYCLES;
    CpuTimer2Regs.TPR.all = 0U;
    CpuTimer2Regs.TPRH.all = 0U;
    CpuTimer2Regs.TCR.bit.FREE = 0U;
    CpuTimer2Regs.TCR.bit.SOFT = 0U;
    CpuTimer2Regs.TCR.bit.TIE = 1U;
    BootUser_CommTimeoutReload();

    EALLOW;
    PieVectTable.TIMER2_INT = &BootUser_CommTimeoutIsr;
    EDIS;

    IER |= M_INT14;
    CpuTimer2Regs.TCR.bit.TSS = 0U;
    __restore_interrupts(interrupt_state);
}

void BootUser_CommTimeoutStop(void)
{
    uint16_t interrupt_state = __disable_interrupts();

    CpuTimer2Regs.TCR.bit.TSS = 1U;
    CpuTimer2Regs.TCR.bit.TIE = 0U;
    IER &= (uint16_t)(~M_INT14);
    CpuTimer2Regs.TCR.bit.TIF = 1U;
    IFR &= (uint16_t)(~M_INT14);
    __restore_interrupts(interrupt_state);
}

void BootUser_CommTimeoutOnValidRequestFrame(void *context)
{
    uint16_t interrupt_state;

    (void)context;
    interrupt_state = __disable_interrupts();
    BootUser_CommTimeoutReload();
    __restore_interrupts(interrupt_state);
}

uint16_t BootUser_CommTimeoutServiceGuardEnter(void *context)
{
    uint16_t interrupt_state;

    (void)context;
    interrupt_state = __disable_interrupts();
    CpuTimer2Regs.TCR.bit.TSS = 1U;
    CpuTimer2Regs.TCR.bit.TIF = 1U;
    IFR &= (uint16_t)(~M_INT14);
    return interrupt_state;
}

void BootUser_CommTimeoutServiceGuardExit(void *context,
                                          uint16_t interrupt_state)
{
    (void)context;
    BootUser_CommTimeoutReload();
    CpuTimer2Regs.TCR.bit.TSS = 0U;
    __restore_interrupts(interrupt_state);
}

__interrupt void BootUser_CommTimeoutIsr(void)
{
    BootUser_ForceDeviceResetNow();

    for (;;)
    {
    }
}
