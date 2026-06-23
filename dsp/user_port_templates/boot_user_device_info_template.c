#include "boot_device_info.h"
#include "boot_protocol.h"

/*
 * USER ACTION REQUIRED: values must match the product linker map and the
 * device_info.json used by the PC. max_data_words must be a positive multiple
 * of eight and must not exceed max_payload_words.
 */
#error "Review and fill product DeviceInfo values before compiling this file"

BootDeviceInfo BootUser_CreateDeviceInfo(void)
{
    BootDeviceInfo info = {0};

    info.device_id = BOOT_DEVICE_F28377D;
    info.cpu_id = BOOT_CPU1;
    info.kernel_ver_major = 0U;
    info.kernel_ver_minor = 1U;
    info.kernel_ver_patch = 0U;
    info.protocol_ver = BOOT_PROTOCOL_VERSION;
    info.feature_flags = 0UL; /* Phase 4 core only; enable Flash features later. */
    info.max_payload_words = BOOT_PROTOCOL_MAX_PAYLOAD_WORDS;
    info.max_data_words = 248U;
    info.boot_mode = BOOT_MODE_FLASH_KERNEL;
    info.kernel_layout = BOOT_KERNEL_LAYOUT_MONOLITHIC;
    return info;
}

