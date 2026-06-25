#ifndef BOOT_RAM_PORT_H
#define BOOT_RAM_PORT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef uint16_t BootRamResult;
typedef uint16_t BootRamRegionType;

#define BOOT_RAM_RESULT_OK                ((BootRamResult)0U)
#define BOOT_RAM_RESULT_NOT_IMPLEMENTED   ((BootRamResult)1U)
#define BOOT_RAM_RESULT_BAD_ADDRESS       ((BootRamResult)2U)
#define BOOT_RAM_RESULT_FAILED            ((BootRamResult)3U)

typedef struct
{
    BootRamRegionType region_type;
    uint32_t address;
    uint32_t length_words;
    uint32_t extra;
} BootRamErrorInfo;

BootRamResult BootRam_CheckAddress(uint32_t address,
                                   uint32_t word_count,
                                   BootRamRegionType region_type,
                                   BootRamErrorInfo *error_info);
BootRamResult BootRam_WriteBlock(uint32_t address,
                                 const uint16_t *data,
                                 uint16_t word_count,
                                 BootRamRegionType region_type,
                                 BootRamErrorInfo *error_info);

#ifdef __cplusplus
}
#endif

#endif
