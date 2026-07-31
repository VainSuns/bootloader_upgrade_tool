//###########################################################################
//
// FILE:   F2837xD_DefaultISR.c
//
// TITLE:  Size-optimized F2837xD default interrupt service routine
//
// Copyright (C) 2013-2024 Texas Instruments Incorporated
// SPDX-License-Identifier: BSD-3-Clause
//
//###########################################################################

#include "F2837xD_device.h"
#include "F2837xD_Examples.h"

//
// All unused vectors share this trap. Used vectors overwrite their entry
// after InitPieVectTable() completes.
//
interrupt void PIE_RESERVED_ISR(void)
{
    asm ("      ESTOP0");
    for(;;)
    {
    }
}
