#include "boot_protocol.h"

#include <stddef.h>

static uint16_t BootProtocol_CrcByte(uint16_t crc, uint16_t byte_value)
{
    uint16_t bit;

    crc ^= (uint16_t)((byte_value & 0x00FFU) << 8U);
    for (bit = 0U; bit < 8U; ++bit)
    {
        if ((crc & 0x8000U) != 0U)
        {
            crc = (uint16_t)((crc << 1U) ^ 0x1021U);
        }
        else
        {
            crc = (uint16_t)(crc << 1U);
        }
    }
    return crc;
}

uint16_t BootProtocol_CrcWords(const uint16_t *words, uint16_t word_count)
{
    uint16_t crc = 0xFFFFU;
    uint16_t index;

    for (index = 0U; index < word_count; ++index)
    {
        crc = BootProtocol_CrcByte(crc, words[index] & 0x00FFU);
        crc = BootProtocol_CrcByte(crc, (uint16_t)(words[index] >> 8U));
    }
    return crc;
}

BootProtocolReceiveResult BootProtocol_Receive(const BootIoOps *io,
                                                BootProtocolFrame *frame)
{
    uint16_t header[BOOT_PROTOCOL_HEADER_WORDS];
    uint16_t have_magic0 = 0U;
    uint16_t index;
    uint16_t received_payload_crc;

    for (;;)
    {
        if (have_magic0 == 0U)
        {
            if (BootIo_GetWord(io) != BOOT_PROTOCOL_MAGIC0)
            {
                continue;
            }
        }

        header[0] = BOOT_PROTOCOL_MAGIC0;
        header[1] = BootIo_GetWord(io);
        if (header[1] != BOOT_PROTOCOL_MAGIC1)
        {
            have_magic0 = (header[1] == BOOT_PROTOCOL_MAGIC0) ? 1U : 0U;
            continue;
        }
        have_magic0 = 0U;

        for (index = 2U; index < BOOT_PROTOCOL_HEADER_WORDS; ++index)
        {
            header[index] = BootIo_GetWord(io);
        }
        if (BootProtocol_CrcWords(header, 9U) != header[9])
        {
            have_magic0 = (header[9] == BOOT_PROTOCOL_MAGIC0) ? 1U : 0U;
            continue;
        }

        frame->protocol_ver = header[2];
        frame->packet_type = header[3];
        frame->command = header[4];
        frame->sequence = header[5];
        frame->flags = header[6];
        frame->status = header[7];
        frame->payload_words = header[8];

        if (frame->payload_words > BOOT_PROTOCOL_MAX_PAYLOAD_WORDS)
        {
            continue;
        }
        for (index = 0U; index < frame->payload_words; ++index)
        {
            frame->payload[index] = BootIo_GetWord(io);
        }
        received_payload_crc = BootIo_GetWord(io);
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

