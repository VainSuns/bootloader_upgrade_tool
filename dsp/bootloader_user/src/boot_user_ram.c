#include "boot_ram_port.h"

/*
 * FUTURE USER ACTION REQUIRED. MVP does not load the RAM service library.
 * Define allowed regions and writes only when that future feature is approved.
 */

BootRamResult BootRam_CheckAddress(uint32_t address,
                                   uint32_t word_count,
                                   BootRamRegionType region_type,
                                   BootRamErrorInfo *error_info)
{
    (void)address;
    (void)word_count;
    (void)region_type;
    (void)error_info;
    return BOOT_RAM_RESULT_NOT_IMPLEMENTED;
}

BootRamResult BootRam_WriteBlock(uint32_t address,
                                 const uint16_t *data,
                                 uint16_t word_count,
                                 BootRamRegionType region_type,
                                 BootRamErrorInfo *error_info)
{
    (void)address;
    (void)data;
    (void)word_count;
    (void)region_type;
    (void)error_info;
    return BOOT_RAM_RESULT_NOT_IMPLEMENTED;
}

