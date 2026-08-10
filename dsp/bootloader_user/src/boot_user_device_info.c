
#include "F28x_Project.h"
#include "boot_device_info.h"
#include "boot_protocol.h"
#include "boot_user_feature_config.h"

/*
 * USER ACTION REQUIRED: values must match the product linker map and the
 * device_info.json used by the PC. max_data_words must be a positive multiple
 * of eight and max_data_words + 5 must fit max_payload_words. Populate the
 * complete identity here; algorithm core must not read DevCfgRegs/UidRegs.
 */
uint16_t BootUser_CreateDeviceInfo(BootDeviceInfo *info)
{
    if (info == 0)
    {
        return 0U;
    }

    info->device_id = BOOT_DEVICE_F28377D;
    info->cpu_id = BOOT_CPU1;
    info->kernel_ver_major = 0U;
    info->kernel_ver_minor = 1U;
    info->kernel_ver_patch = 0U;
    info->protocol_ver = BOOT_PROTOCOL_VERSION;
    info->feature_flags = BOOT_FEATURE_ERASE |
                          BOOT_FEATURE_PROGRAM |
                          BOOT_FEATURE_VERIFY |
                          BOOT_FEATURE_RUN |
                          BOOT_FEATURE_METADATA;
#if BOOT_ENABLE_MEMORY_READ
    info->feature_flags |= BOOT_FEATURE_MEMORY_READ;
#endif
    info->max_payload_words = BOOT_PROTOCOL_MAX_PAYLOAD_WORDS;
    info->max_data_words = 248U;
#ifdef _FLASH
    info->boot_mode = BOOT_MODE_FLASH_KERNEL;
    info->kernel_layout = BOOT_KERNEL_LAYOUT_CORE_RAM_LIB;
#else
    info->boot_mode = BOOT_MODE_RAM_KERNEL;
    info->kernel_layout = BOOT_KERNEL_LAYOUT_MONOLITHIC;
#endif

    /*
     * USER: populate only in this port from:
     * DevCfgRegs.PARTIDL/PARTIDH/REVID and
     * UidRegs.UID_UNIQUE/UID_CHECKSUM/UID_PSRAND0..5.
     */
    #ifdef CPU1
    info->identity.part_id_low = DevCfgRegs.PARTIDL.all;
    info->identity.part_id_high = DevCfgRegs.PARTIDH.all;
    info->identity.revision_id = DevCfgRegs.REVID;
    #else
    info->identity.part_id_low = 0UL;
    info->identity.part_id_high = 0UL;
    info->identity.revision_id = 0UL;
    #endif
    info->identity.uid_unique = UidRegs.UID_UNIQUE;
    info->identity.uid_checksum = UidRegs.UID_CHECKSUM;
    info->identity.uid_psrand[0] = UidRegs.UID_PSRAND0;
    info->identity.uid_psrand[1] = UidRegs.UID_PSRAND1;
    info->identity.uid_psrand[2] = UidRegs.UID_PSRAND2;
    info->identity.uid_psrand[3] = UidRegs.UID_PSRAND3;
    info->identity.uid_psrand[4] = UidRegs.UID_PSRAND4;
    info->identity.uid_psrand[5] = UidRegs.UID_PSRAND5;
    return 1U;
}
