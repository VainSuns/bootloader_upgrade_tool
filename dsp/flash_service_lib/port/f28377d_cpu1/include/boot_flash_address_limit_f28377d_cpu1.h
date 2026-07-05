#ifndef BOOT_USER_ADDRESS_LIMIT_H
#define BOOT_USER_ADDRESS_LIMIT_H

/*
 * Phase 10.2A Slot A layout, in C28x 16-bit word addresses.
 *
 * Flash B still belongs to the allowed erase mask, because it contains both
 * the metadata journal and the first part of the App slot. App Program/Verify
 * payloads use BOOT_USER_SLOT_A_APP_START and must not write metadata words.
 */
#define BOOT_USER_SLOT_A_REGION_START          0x082000UL
#define BOOT_USER_SLOT_A_METADATA_START        0x082000UL
#define BOOT_USER_SLOT_A_METADATA_WORDS        1024UL
#define BOOT_USER_SLOT_A_METADATA_END          0x082400UL

#define BOOT_USER_SLOT_A_APP_START             0x082400UL
#define BOOT_USER_SLOT_A_APP_END_EXCLUSIVE     0x0C0000UL

#define BOOT_USER_APP_FLASH_START              BOOT_USER_SLOT_A_APP_START
#define BOOT_USER_APP_FLASH_END_EXCLUSIVE      BOOT_USER_SLOT_A_APP_END_EXCLUSIVE
#define BOOT_USER_ALLOWED_ERASE_MASK           0x00003FFEUL

#endif
