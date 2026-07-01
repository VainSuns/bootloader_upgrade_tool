#ifndef BOOT_PROTOCOL_H
#define BOOT_PROTOCOL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BOOT_PROTOCOL_MAGIC0              ((uint16_t)0xA55AU)
#define BOOT_PROTOCOL_MAGIC1              ((uint16_t)0x5AA5U)
#define BOOT_PROTOCOL_VERSION             ((uint16_t)0x0001U)
#define BOOT_PROTOCOL_HEADER_WORDS        ((uint16_t)10U)
#define BOOT_PROTOCOL_FLAG_NONE           ((uint16_t)0x0000U)

#ifndef BOOT_PROTOCOL_MAX_PAYLOAD_WORDS
#define BOOT_PROTOCOL_MAX_PAYLOAD_WORDS   ((uint16_t)256U)
#endif

#define BOOT_PKT_REQUEST                  ((uint16_t)0x0001U)
#define BOOT_PKT_RESPONSE                 ((uint16_t)0x0002U)
#define BOOT_PKT_ERROR_RESPONSE           ((uint16_t)0x0003U)

#define BOOT_CMD_PING                     ((uint16_t)0x0001U)
#define BOOT_CMD_GET_DEVICE_INFO          ((uint16_t)0x0002U)
#define BOOT_CMD_GET_PROTOCOL_INFO        ((uint16_t)0x0003U)
#define BOOT_CMD_GET_LAST_ERROR           ((uint16_t)0x0004U)
#define BOOT_CMD_RAM_LOAD_BEGIN           ((uint16_t)0x0101U)
#define BOOT_CMD_RAM_LOAD_DATA            ((uint16_t)0x0102U)
#define BOOT_CMD_RAM_LOAD_END             ((uint16_t)0x0103U)
#define BOOT_CMD_ERASE                    ((uint16_t)0x0201U)
#define BOOT_CMD_PROGRAM_BEGIN            ((uint16_t)0x0210U)
#define BOOT_CMD_PROGRAM_DATA             ((uint16_t)0x0211U)
#define BOOT_CMD_PROGRAM_END              ((uint16_t)0x0212U)
#define BOOT_CMD_VERIFY_BEGIN             ((uint16_t)0x0220U)
#define BOOT_CMD_VERIFY_DATA              ((uint16_t)0x0221U)
#define BOOT_CMD_VERIFY_END               ((uint16_t)0x0222U)
#define BOOT_CMD_FLASH_READ               ((uint16_t)0x0230U)
#define BOOT_CMD_RUN                      ((uint16_t)0x0301U)
#define BOOT_CMD_RESET                    ((uint16_t)0x0302U)

#define BOOT_TARGET_FLASH_APP             ((uint16_t)0x0001U)
#define BOOT_TARGET_RAM_APP               ((uint16_t)0x0002U)

#define BOOT_READ_TARGET_METADATA         ((uint16_t)0x0001U)
#define BOOT_READ_TARGET_APP              ((uint16_t)0x0002U)
#define BOOT_READ_TARGET_RAW_FLASH        ((uint16_t)0x0003U)

#define BOOT_STATUS_OK                    ((uint16_t)0x0000U)
#define BOOT_STATUS_BAD_PAYLOAD_CRC       ((uint16_t)0x0103U)
#define BOOT_STATUS_UNSUPPORTED_PROTOCOL  ((uint16_t)0x0104U)
#define BOOT_STATUS_BAD_PACKET_TYPE       ((uint16_t)0x0105U)
#define BOOT_STATUS_BAD_PAYLOAD_LENGTH    ((uint16_t)0x0106U)
#define BOOT_STATUS_BAD_FLAGS             ((uint16_t)0x0109U)
#define BOOT_STATUS_UNKNOWN_COMMAND       ((uint16_t)0x0201U)
#define BOOT_STATUS_UNSUPPORTED_COMMAND   ((uint16_t)0x0202U)
#define BOOT_STATUS_INVALID_STATE         ((uint16_t)0x0203U)
#define BOOT_STATUS_BUSY                  ((uint16_t)0x0204U)
#define BOOT_STATUS_MISSING_BEGIN         ((uint16_t)0x0205U)
#define BOOT_STATUS_UNEXPECTED_END        ((uint16_t)0x0206U)
#define BOOT_STATUS_BLOCK_INDEX_ERROR     ((uint16_t)0x0207U)
#define BOOT_STATUS_TOTAL_COUNT_MISMATCH  ((uint16_t)0x0208U)
#define BOOT_STATUS_BAD_ADDRESS           ((uint16_t)0x0301U)
#define BOOT_STATUS_ADDRESS_OUT_OF_RANGE  ((uint16_t)0x0302U)
#define BOOT_STATUS_BAD_ALIGNMENT         ((uint16_t)0x0303U)
#define BOOT_STATUS_BAD_WORD_COUNT        ((uint16_t)0x0304U)
#define BOOT_STATUS_PROTECTED_REGION      ((uint16_t)0x0305U)
#define BOOT_STATUS_ERASE_FAILED          ((uint16_t)0x0401U)
#define BOOT_STATUS_ERASE_FSM_ERROR       ((uint16_t)0x0402U)
#define BOOT_STATUS_BLANK_CHECK_FAILED    ((uint16_t)0x0403U)
#define BOOT_STATUS_PROGRAM_FAILED        ((uint16_t)0x0501U)
#define BOOT_STATUS_PROGRAM_FSM_ERROR     ((uint16_t)0x0502U)
#define BOOT_STATUS_PROGRAM_VERIFY_FAILED ((uint16_t)0x0503U)
#define BOOT_STATUS_REPROGRAM_FORBIDDEN   ((uint16_t)0x0504U)
#define BOOT_STATUS_VERIFY_FAILED         ((uint16_t)0x0601U)
#define BOOT_STATUS_VERIFY_MISMATCH       ((uint16_t)0x0602U)
#define BOOT_STATUS_RAM_ADDRESS_ERROR     ((uint16_t)0x0701U)
#define BOOT_STATUS_RAM_WRITE_FAILED      ((uint16_t)0x0702U)
#define BOOT_STATUS_RAM_REGION_ERROR      ((uint16_t)0x0703U)
#define BOOT_STATUS_UNSUPPORTED_FEATURE   ((uint16_t)0x0801U)
#define BOOT_STATUS_DEVICE_INFO_UNAVAILABLE ((uint16_t)0x0802U)
#define BOOT_STATUS_TARGET_MISMATCH       ((uint16_t)0x0803U)
#define BOOT_STATUS_SECURITY_LOCKED       ((uint16_t)0x0901U)
#define BOOT_STATUS_UNLOCK_FAILED         ((uint16_t)0x0902U)
#define BOOT_STATUS_USER_ERROR_BASE       ((uint16_t)0x7F00U)

typedef struct
{
    uint16_t protocol_ver;
    uint16_t packet_type;
    uint16_t command;
    uint16_t sequence;
    uint16_t flags;
    uint16_t status;
    uint16_t payload_words;
    uint16_t payload[BOOT_PROTOCOL_MAX_PAYLOAD_WORDS];
} BootProtocolFrame;

typedef enum
{
    BOOT_PROTOCOL_RECEIVE_OK = 0,
    BOOT_PROTOCOL_RECEIVE_BAD_PAYLOAD_CRC = 1
} BootProtocolReceiveResult;

uint16_t BootProtocol_CrcWords(const uint16_t *words, uint16_t word_count);

#ifdef __cplusplus
}
#endif

#endif
