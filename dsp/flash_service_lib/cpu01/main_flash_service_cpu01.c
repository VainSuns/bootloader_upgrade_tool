#include <stdint.h>

#include "boot_flash_service_lib.h"

void BootFlashServiceLib_ServiceImageEntry(void)
{
    volatile uint16_t hold = 1U;
    while (hold != 0U)
    {
    }
}

int main(void)
{
    BootFlashServiceLib_ServiceImageEntry();
    return 0;
}
