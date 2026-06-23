#ifndef BOOT_PROTOCOL_H
#define BOOT_PROTOCOL_H

#include <stdint.h>

#include "boot_io.h"

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
#define BOOT_CMD_RUN                      ((uint16_t)0x0301U)
#define BOOT_CMD_RESET                    ((uint16_t)0x0302U)

#define BOOT_STATUS_OK                    ((uint16_t)0x0000U)
#define BOOT_STATUS_BAD_PAYLOAD_CRC       ((uint16_t)0x0103U)
#define BOOT_STATUS_UNSUPPORTED_PROTOCOL  ((uint16_t)0x0104U)
#define BOOT_STATUS_BAD_PACKET_TYPE       ((uint16_t)0x0105U)
#define BOOT_STATUS_BAD_PAYLOAD_LENGTH    ((uint16_t)0x0106U)
#define BOOT_STATUS_BAD_FLAGS             ((uint16_t)0x0109U)
#define BOOT_STATUS_UNKNOWN_COMMAND       ((uint16_t)0x0201U)
#define BOOT_STATUS_UNSUPPORTED_COMMAND   ((uint16_t)0x0202U)

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
BootProtocolReceiveResult BootProtocol_Receive(const BootIoOps *io,
                                                BootProtocolFrame *frame);
void BootProtocol_SendResponse(const BootIoOps *io,
                               const BootProtocolFrame *request,
                               uint16_t packet_type,
                               uint16_t status,
                               const uint16_t *payload,
                               uint16_t payload_words);

#ifdef __cplusplus
}
#endif

#endif

