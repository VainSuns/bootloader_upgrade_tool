#ifndef BOOT_DEVICE_INFO_H
#define BOOT_DEVICE_INFO_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BOOT_DEVICE_INFO_WORDS            ((uint16_t)16U)
#define BOOT_PROTOCOL_INFO_WORDS          ((uint16_t)8U)
#define BOOT_ERROR_DETAIL_WORDS           ((uint16_t)11U)

#define BOOT_DEVICE_UNKNOWN               ((uint16_t)0x0000U)
#define BOOT_DEVICE_F28377D               ((uint16_t)0x377DU)
#define BOOT_CPU_UNKNOWN                  ((uint16_t)0x0000U)
#define BOOT_CPU1                         ((uint16_t)0x0001U)
#define BOOT_CPU2                         ((uint16_t)0x0002U)
#define BOOT_MODE_UNKNOWN                 ((uint16_t)0x0000U)
#define BOOT_MODE_RAM_KERNEL              ((uint16_t)0x0001U)
#define BOOT_MODE_FLASH_KERNEL            ((uint16_t)0x0002U)
#define BOOT_KERNEL_LAYOUT_UNKNOWN        ((uint16_t)0x0000U)
#define BOOT_KERNEL_LAYOUT_MONOLITHIC     ((uint16_t)0x0001U)
#define BOOT_KERNEL_LAYOUT_CORE_RAM_LIB   ((uint16_t)0x0002U)

#define BOOT_FEATURE_ERASE                ((uint32_t)1UL << 0)
#define BOOT_FEATURE_PROGRAM              ((uint32_t)1UL << 1)
#define BOOT_FEATURE_VERIFY               ((uint32_t)1UL << 2)
#define BOOT_FEATURE_RUN                  ((uint32_t)1UL << 3)
#define BOOT_FEATURE_RESET                ((uint32_t)1UL << 4)
#define BOOT_FEATURE_RAM_LOAD             ((uint32_t)1UL << 5)

#define BOOT_ERR_OP_NONE                  ((uint16_t)0x0000U)
#define BOOT_ERR_OP_FRAME                 ((uint16_t)0x0001U)
#define BOOT_ERR_OP_ERASE                 ((uint16_t)0x0002U)
#define BOOT_ERR_OP_PROGRAM               ((uint16_t)0x0003U)
#define BOOT_ERR_OP_VERIFY                ((uint16_t)0x0004U)
#define BOOT_ERR_OP_RAM_LOAD              ((uint16_t)0x0005U)
#define BOOT_ERR_OP_RUN                   ((uint16_t)0x0006U)
#define BOOT_ERR_OP_RESET                 ((uint16_t)0x0007U)

#define BOOT_ERR_STAGE_NONE               ((uint16_t)0x0000U)
#define BOOT_ERR_STAGE_HEADER             ((uint16_t)0x0001U)
#define BOOT_ERR_STAGE_PAYLOAD            ((uint16_t)0x0002U)
#define BOOT_ERR_STAGE_ADDRESS_CHECK      ((uint16_t)0x0003U)
#define BOOT_ERR_STAGE_API_CALL           ((uint16_t)0x0004U)
#define BOOT_ERR_STAGE_FSM                ((uint16_t)0x0005U)
#define BOOT_ERR_STAGE_VERIFY             ((uint16_t)0x0006U)
#define BOOT_ERR_STAGE_STATE              ((uint16_t)0x0007U)

typedef struct
{
    uint16_t device_id;
    uint16_t cpu_id;
    uint16_t kernel_ver_major;
    uint16_t kernel_ver_minor;
    uint16_t kernel_ver_patch;
    uint16_t protocol_ver;
    uint32_t feature_flags;
    uint16_t max_payload_words;
    uint16_t max_data_words;
    uint16_t boot_mode;
    uint16_t kernel_layout;
    uint16_t reserved[4];
} BootDeviceInfo;

typedef struct
{
    uint16_t operation;
    uint16_t stage;
    uint32_t address;
    uint32_t length_words;
    uint16_t api_status;
    uint32_t fsm_status;
    uint16_t extra0;
    uint16_t extra1;
} BootErrorDetail;

void BootDeviceInfo_ToPayload(const BootDeviceInfo *info,
                              uint16_t payload[BOOT_DEVICE_INFO_WORDS]);
void BootErrorDetail_Clear(BootErrorDetail *detail);
void BootErrorDetail_ToPayload(const BootErrorDetail *detail,
                               uint16_t payload[BOOT_ERROR_DETAIL_WORDS]);

#ifdef __cplusplus
}
#endif

#endif
