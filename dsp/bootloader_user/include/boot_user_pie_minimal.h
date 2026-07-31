#ifndef BOOT_USER_PIE_MINIMAL_H
#define BOOT_USER_PIE_MINIMAL_H

void BootUser_InitPieCtrlMinimal(void);
void BootUser_InitPieVectTableMinimal(void);
__interrupt void BootUser_PieReservedIsr(void);

#endif
