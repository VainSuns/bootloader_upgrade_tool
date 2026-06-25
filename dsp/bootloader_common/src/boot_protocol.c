#include "boot_protocol.h"

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
