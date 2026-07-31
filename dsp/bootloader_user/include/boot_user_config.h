#ifndef BOOT_USER_CONFIG_H
#define BOOT_USER_CONFIG_H

#include "boot_flash_service_layout.h"

#define BOOT_USER_TIMEOUT_MS              (60000UL)  /* Timeout for host communication in milliseconds. */  
#ifndef BOOT_USER_CPU_SYSCLK_HZ
#define BOOT_USER_CPU_SYSCLK_HZ           200000000UL
#endif

#ifndef BOOT_USER_COMM_TIMEOUT_MS
#define BOOT_USER_COMM_TIMEOUT_MS         15000UL
#endif

#define BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS \
    BOOT_FLASH_SERVICE_HEADER_ORIGIN
#define BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS \
    BOOT_FLASH_SERVICE_PUBLISH_ORIGIN

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
