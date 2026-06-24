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
    uint16_t header_words = 0U;
    uint16_t index;
    uint16_t start;
    uint16_t word;
    uint16_t received_payload_crc;

    for (;;)
    {
        while (header_words < 2U)
        {
            word = BootIo_GetWord(io);
            if (header_words == 0U)
            {
                if (word == BOOT_PROTOCOL_MAGIC0)
                {
                    header[header_words++] = word;
                }
            }
            else if (word == BOOT_PROTOCOL_MAGIC1)
            {
                header[header_words++] = word;
            }
            else if (word != BOOT_PROTOCOL_MAGIC0)
            {
                header_words = 0U;
            }
        }

        while (header_words < BOOT_PROTOCOL_HEADER_WORDS)
        {
            header[header_words++] = BootIo_GetWord(io);
        }

        if ((BootProtocol_CrcWords(header, 9U) != header[9]) ||
            (header[8] > BOOT_PROTOCOL_MAX_PAYLOAD_WORDS))
        {
            header_words = 0U;
            for (start = 1U; start + 1U < BOOT_PROTOCOL_HEADER_WORDS; ++start)
            {
                if ((header[start] == BOOT_PROTOCOL_MAGIC0) &&
                    (header[start + 1U] == BOOT_PROTOCOL_MAGIC1))
                {
                    header_words = (uint16_t)(BOOT_PROTOCOL_HEADER_WORDS - start);
                    for (index = 0U; index < header_words; ++index)
                    {
                        header[index] = header[start + index];
                    }
                    break;
                }
            }
            if ((header_words == 0U) &&
                (header[BOOT_PROTOCOL_HEADER_WORDS - 1U] == BOOT_PROTOCOL_MAGIC0))
            {
                header[0] = BOOT_PROTOCOL_MAGIC0;
                header_words = 1U;
            }
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
