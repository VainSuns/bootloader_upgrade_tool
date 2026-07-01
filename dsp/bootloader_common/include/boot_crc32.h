#ifndef BOOT_CRC32_H
#define BOOT_CRC32_H

#include <stdint.h>

#define BOOT_CRC32_INIT_VALUE   0xFFFFFFFFUL
#define BOOT_CRC32_XOROUT_VALUE 0xFFFFFFFFUL

uint32_t BootCrc32_UpdateByte(uint32_t crc, uint16_t byte_value);
uint32_t BootCrc32_UpdateWord(uint32_t crc, uint16_t word_value);
uint32_t BootCrc32_Finalize(uint32_t crc);
uint32_t BootCrc32_CalcWords(const uint16_t *words, uint32_t word_count);

#endif
