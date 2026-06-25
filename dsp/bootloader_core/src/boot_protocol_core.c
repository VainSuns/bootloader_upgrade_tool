#include "boot_protocol_core.h"

#include <stddef.h>

static void BootProtocol_FindMagicBytes(const BootIoOps *io)
{
    static const uint16_t magic_bytes[4] = {0x5AU, 0xA5U, 0xA5U, 0x5AU};
    uint16_t matched = 0U;
    uint16_t byte_value;

    for (;;)
    {
        byte_value = BootIo_GetByte(io);
        if (byte_value == magic_bytes[matched])
        {
            ++matched;
            if (matched == 4U)
            {
                return;
            }
        }
        else
        {
            matched = (byte_value == magic_bytes[0]) ? 1U : 0U;
        }
    }
}

static uint16_t BootProtocol_ReadWordFromBytes(const BootIoOps *io)
{
    uint16_t low = BootIo_GetByte(io);
    uint16_t high = BootIo_GetByte(io);
    return (uint16_t)(low | (uint16_t)(high << 8U));
}

BootProtocolReceiveResult BootProtocol_Receive(const BootIoOps *io,
                                                BootProtocolFrame *frame)
{
    uint16_t header[BOOT_PROTOCOL_HEADER_WORDS];
    uint16_t index;
    uint16_t received_payload_crc;

    for (;;)
    {
        BootProtocol_FindMagicBytes(io);
        header[0] = BOOT_PROTOCOL_MAGIC0;
        header[1] = BOOT_PROTOCOL_MAGIC1;
        for (index = 2U; index < BOOT_PROTOCOL_HEADER_WORDS; ++index)
        {
            header[index] = BootProtocol_ReadWordFromBytes(io);
        }

        if ((BootProtocol_CrcWords(header, 9U) != header[9]) ||
            (header[8] > BOOT_PROTOCOL_MAX_PAYLOAD_WORDS))
        {
            continue;
        }

        frame->protocol_ver = header[2];
        frame->packet_type = header[3];
        frame->command = header[4];
        frame->sequence = header[5];
        frame->flags = header[6];
        frame->status = header[7];
        frame->payload_words = header[8];

        for (index = 0U; index < frame->payload_words; ++index)
        {
            frame->payload[index] = BootProtocol_ReadWordFromBytes(io);
        }
        received_payload_crc = BootProtocol_ReadWordFromBytes(io);
        if (BootProtocol_CrcWords(frame->payload, frame->payload_words) != received_payload_crc)
        {
            return BOOT_PROTOCOL_RECEIVE_BAD_PAYLOAD_CRC;
        }
        return BOOT_PROTOCOL_RECEIVE_OK;
    }
}

void BootProtocol_SendResponse(const BootIoOps *io,
                               const BootProtocolFrame *request,
                               uint16_t packet_type,
                               uint16_t status,
                               const uint16_t *payload,
                               uint16_t payload_words)
{
    uint16_t header[9];
    uint16_t index;

    header[0] = BOOT_PROTOCOL_MAGIC0;
    header[1] = BOOT_PROTOCOL_MAGIC1;
    header[2] = BOOT_PROTOCOL_VERSION;
    header[3] = packet_type;
    header[4] = request->command;
    header[5] = request->sequence;
    header[6] = BOOT_PROTOCOL_FLAG_NONE;
    header[7] = status;
    header[8] = payload_words;

    for (index = 0U; index < 9U; ++index)
    {
        BootIo_SendWord(io, header[index]);
    }
    BootIo_SendWord(io, BootProtocol_CrcWords(header, 9U));
    for (index = 0U; index < payload_words; ++index)
    {
        BootIo_SendWord(io, payload[index]);
    }
    BootIo_SendWord(io, BootProtocol_CrcWords(payload, payload_words));
}
