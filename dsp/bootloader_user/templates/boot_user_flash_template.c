#include "boot_flash_port.h"

/*
 * USER ACTION REQUIRED. This file is the only intended raw Flash integration
 * boundary. Implement it using the product-reviewed TI F021 port and RAM-safe
 * call chain. Preserve API status, FMSTAT, failing address, and operation in
 * BootFlashErrorInfo. Do not auto-retry programming.
 */
#error "Implement and review the product BootFlash_* port before compiling this file"

BootFlashResult BootFlash_Init(BootFlashErrorInfo *error_info)
{
    (void)error_info;
    /* Return INIT_FAILED when the underlying Flash API initialization fails. */
    return BOOT_FLASH_RESULT_INIT_FAILED;
}

BootFlashResult BootFlash_CheckAddress(uint32_t address,
                                       uint32_t word_count,
                                       BootFlashOperation operation,
                                       BootFlashErrorInfo *error_info)
{
    (void)address;
    (void)word_count;
    (void)operation;
    (void)error_info;
    return BOOT_FLASH_RESULT_NOT_IMPLEMENTED;
}

BootFlashResult BootFlash_EraseBySectorMask(uint32_t sector_mask,
                                            BootFlashErrorInfo *error_info)
{
    (void)sector_mask;
    (void)error_info;
    return BOOT_FLASH_RESULT_NOT_IMPLEMENTED;
}

BootFlashResult BootFlash_ProgramBlock(uint32_t address,
                                       const uint16_t *data,
                                       uint16_t word_count,
                                       BootFlashErrorInfo *error_info)
{
    (void)address;
    (void)data;
    (void)word_count;
    (void)error_info;
    return BOOT_FLASH_RESULT_NOT_IMPLEMENTED;
}

BootFlashResult BootFlash_VerifyBlock(uint32_t address,
                                      const uint16_t *expected,
                                      uint16_t word_count,
                                      BootFlashErrorInfo *error_info)
{
    (void)address;
    (void)expected;
    (void)word_count;
    (void)error_info;
    return BOOT_FLASH_RESULT_NOT_IMPLEMENTED;
}
