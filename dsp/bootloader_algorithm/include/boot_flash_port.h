#ifndef BOOT_FLASH_PORT_H
#define BOOT_FLASH_PORT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef uint16_t BootFlashResult;

#define BOOT_FLASH_RESULT_OK              ((BootFlashResult)0U)
#define BOOT_FLASH_RESULT_NOT_IMPLEMENTED ((BootFlashResult)1U)
#define BOOT_FLASH_RESULT_BAD_ADDRESS     ((BootFlashResult)2U)
#define BOOT_FLASH_RESULT_FAILED          ((BootFlashResult)3U)

typedef enum
{
    BOOT_FLASH_OP_NONE = 0,
    BOOT_FLASH_OP_ERASE = 1,
    BOOT_FLASH_OP_PROGRAM = 2,
    BOOT_FLASH_OP_VERIFY = 3
} BootFlashOperation;

typedef struct
{
    BootFlashOperation operation;
    uint32_t address;
    uint32_t length_words;
    int32_t api_status;
    uint32_t fsm_status;
    uint32_t extra;
} BootFlashErrorInfo;

BootFlashResult BootFlash_CheckAddress(uint32_t address,
                                       uint32_t word_count,
                                       BootFlashOperation operation,
                                       BootFlashErrorInfo *error_info);
BootFlashResult BootFlash_EraseBySectorMask(uint32_t sector_mask_low,
                                            uint32_t sector_mask_high,
                                            BootFlashErrorInfo *error_info);
BootFlashResult BootFlash_ProgramBlock(uint32_t address,
                                       const uint16_t *data,
                                       uint16_t word_count,
                                       BootFlashErrorInfo *error_info);
BootFlashResult BootFlash_VerifyBlock(uint32_t address,
                                      const uint16_t *expected,
                                      uint16_t word_count,
                                      BootFlashErrorInfo *error_info);

#ifdef __cplusplus
}
#endif

#endif

