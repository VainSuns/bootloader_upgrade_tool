#ifndef BOOT_USER_CONFIG_H
#define BOOT_USER_CONFIG_H

#define BOOT_USER_TIMEOUT_MS              (60000UL)  /* Timeout for host communication in milliseconds. */  

#ifndef BOOT_USER_AUTO_BOOT_ENABLE
#define BOOT_USER_AUTO_BOOT_ENABLE          0U
#endif

#ifndef BOOT_USER_GUI_WAIT_WINDOW_MS
#define BOOT_USER_GUI_WAIT_WINDOW_MS        5000UL
#endif

#ifndef BOOT_USER_SERVICE_DESCRIPTOR_ADDRESS
#define BOOT_USER_SERVICE_DESCRIPTOR_ADDRESS 0x00013000UL
#endif


//
// User can enable/disable bootloader I/O interfaces here.
//
#define BOOT_USER_IO_SCI_ENABLE              (1U)     /* Enable SCI bootloader I/O. */

#endif
