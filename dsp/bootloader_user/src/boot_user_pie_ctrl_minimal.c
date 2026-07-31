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
 * Project-adapted, size-minimized implementation for the
 * TMS320F28377D CPU1 Flash-resident bootloader.
 * Derived from TI F2837xD device-support examples; this is not an
 * unmodified TI source file.
 */

#include "F2837xD_device.h"
#include "F2837xD_Examples.h"
#include "boot_user_pie_minimal.h"

void BootUser_InitPieCtrlMinimal(void)
{
    DINT;

    PieCtrlRegs.PIECTRL.bit.ENPIE = 0U;

    PieCtrlRegs.PIEIER1.all = 0U;
    PieCtrlRegs.PIEIER2.all = 0U;
    PieCtrlRegs.PIEIER3.all = 0U;
    PieCtrlRegs.PIEIER4.all = 0U;
    PieCtrlRegs.PIEIER5.all = 0U;
    PieCtrlRegs.PIEIER6.all = 0U;
    PieCtrlRegs.PIEIER7.all = 0U;
    PieCtrlRegs.PIEIER8.all = 0U;
    PieCtrlRegs.PIEIER9.all = 0U;
    PieCtrlRegs.PIEIER10.all = 0U;
    PieCtrlRegs.PIEIER11.all = 0U;
    PieCtrlRegs.PIEIER12.all = 0U;

    PieCtrlRegs.PIEIFR1.all = 0U;
    PieCtrlRegs.PIEIFR2.all = 0U;
    PieCtrlRegs.PIEIFR3.all = 0U;
    PieCtrlRegs.PIEIFR4.all = 0U;
    PieCtrlRegs.PIEIFR5.all = 0U;
    PieCtrlRegs.PIEIFR6.all = 0U;
    PieCtrlRegs.PIEIFR7.all = 0U;
    PieCtrlRegs.PIEIFR8.all = 0U;
    PieCtrlRegs.PIEIFR9.all = 0U;
    PieCtrlRegs.PIEIFR10.all = 0U;
    PieCtrlRegs.PIEIFR11.all = 0U;
    PieCtrlRegs.PIEIFR12.all = 0U;
}
