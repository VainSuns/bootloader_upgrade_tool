//###########################################################################
//
// FILE:   F2837xD_PieVect.c
//
// TITLE:  Size-optimized F2837xD PIE vector initialization
//
// Copyright (C) 2013-2024 Texas Instruments Incorporated
// SPDX-License-Identifier: BSD-3-Clause
//
//###########################################################################

#include "F2837xD_device.h"
#include "F2837xD_Examples.h"

//
// Initialize every application-owned vector to one shared trap. The first
// three 32-bit entries are Boot ROM variables and must not be overwritten.
//
void InitPieVectTable(void)
{
    Uint16 i;
    Uint32 *dest = (void *)&PieVectTable;
    Uint32 default_isr = (Uint32)&PIE_RESERVED_ISR;

    dest += 3;

    EALLOW;
    for(i = 0U; i < 221U; i++)
    {
        *dest++ = default_isr;
    }
    EDIS;

    PieCtrlRegs.PIECTRL.bit.ENPIE = 1U;
}
