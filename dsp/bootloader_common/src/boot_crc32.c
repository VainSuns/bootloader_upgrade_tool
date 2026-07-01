#include "boot_crc32.h"

#include <stddef.h>

uint32_t BootCrc32_UpdateByte(uint32_t crc, uint16_t byte_value)
{
    uint16_t bit;

    crc ^= (uint32_t)(byte_value & 0x00FFU);
    for (bit = 0U; bit < 8U; bit++)
    {
        if ((crc & 1UL) != 0UL)
        {
            crc = (crc >> 1U) ^ 0xEDB88320UL;
        }
        else
        {
            crc >>= 1U;
        }
    }
    return crc;
}

uint32_t BootCrc32_UpdateWord(uint32_t crc, uint16_t word_value)
{
    crc = BootCrc32_UpdateByte(crc, word_value & 0x00FFU);
    crc = BootCrc32_UpdateByte(crc, (uint16_t)((word_value >> 8U) & 0x00FFU));
    return crc;
}

uint32_t BootCrc32_Finalize(uint32_t crc)
{
    return crc ^ BOOT_CRC32_XOROUT_VALUE;
}

uint32_t BootCrc32_CalcWords(const uint16_t *words, uint32_t word_count)
{
    uint32_t index;
    uint32_t crc = BOOT_CRC32_INIT_VALUE;

    if (words == NULL)
    {
        return BootCrc32_Finalize(crc);
    }

    for (index = 0UL; index < word_count; index++)
    {
        crc = BootCrc32_UpdateWord(crc, words[index]);
    }

    return BootCrc32_Finalize(crc);
}
