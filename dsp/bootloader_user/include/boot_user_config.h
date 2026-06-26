#ifndef BOOT_USER_CONFIG_H
#define BOOT_USER_CONFIG_H

#define BOOT_USER_TIMEOUT_MS              (60000UL)  /* Timeout for host communication in milliseconds. */  


//
// User can enable/disable bootloader I/O interfaces here.
//
#define BOOT_USER_IO_SCI_ENABLE              (1U)     /* Enable SCI bootloader I/O. */


#define BOOT_USER_STATIC_FLASH_SERVICE_ENABLE 1U


#endif
