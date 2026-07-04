/* Minimal RAM_RUN test app template.
 *
 * Link this file into an allowed RAM executable region, then load it with
 * bootloader_upgrade_tool.tools.ram_run. The marker address must stay outside
 * bootloader-owned RAM in the user's linker setup.
 */

#include <stdint.h>

#ifndef RAM_RUN_MARKER_ADDR
#define RAM_RUN_MARKER_ADDR ((volatile uint16_t *)0x0000U)
#endif

void main(void)
{
    *RAM_RUN_MARKER_ADDR = 0xA55AU;
    for (;;)
    {
    }
}

