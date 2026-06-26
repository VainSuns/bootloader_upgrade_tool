#include "boot_ram_port.h"
#include "boot_protocol.h"
#include "boot_user_ram_limit.h"

/*
 * User RAM port for MVP.
 *
 * Rules:
 * - BOOT_TARGET_RAM_APP only.
 * - Address is C28x 16-bit word address.
 * - word_count is 16-bit word count.
 * - end address is exclusive.
 * - Allowed RAM write regions are generated into boot_user_ram_limit.h.
 * - No Flash-style alignment requirement.
 * - No timeout logic.
 * - No watchdog logic.
 * - No dynamic service activation.
 */

static uint16_t BootRam_IsInWriteRegion(uint32_t address,
                                        uint32_t word_count)
{
    uint32_t end_exclusive;

    if (word_count == 0UL)
    {
        return 0U;
    }

    end_exclusive = address + word_count;

    if (end_exclusive < address)
    {
        return 0U;
    }

#if BOOT_USER_RAM_WRITE_REGION_COUNT > 0U
    if (end_exclusive <= BOOT_USER_RAM_WRITE_REGION0_END_EXCLUSIVE)
    {
        return 1U;
    }
#endif

#if BOOT_USER_RAM_WRITE_REGION_COUNT > 1U
    if ((address >= BOOT_USER_RAM_WRITE_REGION1_START) &&
        (end_exclusive <= BOOT_USER_RAM_WRITE_REGION1_END_EXCLUSIVE))
    {
        return 1U;
    }
#endif

#if BOOT_USER_RAM_WRITE_REGION_COUNT > 2U
    if ((address >= BOOT_USER_RAM_WRITE_REGION2_START) &&
        (end_exclusive <= BOOT_USER_RAM_WRITE_REGION2_END_EXCLUSIVE))
    {
        return 1U;
    }
#endif

#if BOOT_USER_RAM_WRITE_REGION_COUNT > 3U
    if ((address >= BOOT_USER_RAM_WRITE_REGION3_START) &&
        (end_exclusive <= BOOT_USER_RAM_WRITE_REGION3_END_EXCLUSIVE))
    {
        return 1U;
    }
#endif

#if BOOT_USER_RAM_WRITE_REGION_COUNT > 4U
    if ((address >= BOOT_USER_RAM_WRITE_REGION4_START) &&
        (end_exclusive <= BOOT_USER_RAM_WRITE_REGION4_END_EXCLUSIVE))
    {
        return 1U;
    }
#endif

#if BOOT_USER_RAM_WRITE_REGION_COUNT > 5U
    if ((address >= BOOT_USER_RAM_WRITE_REGION5_START) &&
        (end_exclusive <= BOOT_USER_RAM_WRITE_REGION5_END_EXCLUSIVE))
    {
        return 1U;
}
#endif

#if BOOT_USER_RAM_WRITE_REGION_COUNT > 6U
    if ((address >= BOOT_USER_RAM_WRITE_REGION6_START) &&
        (end_exclusive <= BOOT_USER_RAM_WRITE_REGION6_END_EXCLUSIVE))
    {
        return 1U;
    }
#endif

#if BOOT_USER_RAM_WRITE_REGION_COUNT > 7U
#error "Increase BootRam_IsInWriteRegion() region checks"
#endif

    return 0U;
}

BootRamResult BootRam_CheckAddress(uint32_t address,
                                   uint32_t word_count,
                                   BootRamRegionType region_type,
                                   BootRamErrorInfo *error_info)
{
    BootRamResult result = BOOT_RAM_RESULT_OK;

    do
    {
        if (region_type != BOOT_TARGET_RAM_APP)
        {
            result = BOOT_RAM_RESULT_BAD_ADDRESS;
            break;
        }

        if (BootRam_IsInWriteRegion(address, word_count) == 0U)
        {
            result = BOOT_RAM_RESULT_BAD_ADDRESS;
            break;
        }
    } while (0);

    if ((result != BOOT_RAM_RESULT_OK) && (error_info != 0))
    {
        error_info->region_type = region_type;
        error_info->address = address;
        error_info->length_words = word_count;
        error_info->extra = 0UL;
    }

    return result;
}

BootRamResult BootRam_WriteBlock(uint32_t address,
                                 const uint16_t *data,
                                 uint16_t word_count,
                                 BootRamRegionType region_type,
                                 BootRamErrorInfo *error_info)
{
    volatile uint16_t *dst;
    uint16_t i;

    if (BootRam_CheckAddress(address, word_count, region_type, error_info) !=
        BOOT_RAM_RESULT_OK)
    {
        return BOOT_RAM_RESULT_BAD_ADDRESS;
    }

    (void)error_info;

    dst = (volatile uint16_t *)address;

    for (i = 0U; i < word_count; ++i)
    {
        dst[i] = data[i];
    }

    return BOOT_RAM_RESULT_OK;
}
