#ifndef BOOT_USER_CONFIG_H
#define BOOT_USER_CONFIG_H

#define BOOT_USER_TIMEOUT_MS              (60000UL)  /* Timeout for host communication in milliseconds. */  
#define BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS  0x013000UL
#define BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS 0x013020UL

#ifndef BOOT_USER_AUTO_BOOT_ENABLE
#define BOOT_USER_AUTO_BOOT_ENABLE          0U
#endif

#ifndef BOOT_USER_GUI_WAIT_WINDOW_MS
#define BOOT_USER_GUI_WAIT_WINDOW_MS        5000UL
#endif


//
// User can enable/disable bootloader I/O interfaces here.
//
#define BOOT_USER_IO_SCI_ENABLE              (1U)     /* Enable SCI bootloader I/O. */

#endif
