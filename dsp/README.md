# DSP Source

The DSP tree preserves the Flash-resident kernel core / RAM-resident service
library boundary. Phase 4 provides the hardware-independent connection,
protocol, and DeviceInfo core plus guarded user-port templates. Low-level
initialization, linker placement, raw F021 API, and Flash operations remain
user-owned and are not implemented here.

Top-level layout:

- `bootloader_common/`: shared ABI, protocol constants/types, DeviceInfo, port headers, pure helpers.
- `bootloader_core/`: Flash-resident protocol/IO/core command handling.
- `bootloader_user/`: product-owned CPU1 integration, SCI/device-info ports, and templates.
- `flash_service_lib/`: RAM-resident Flash Erase/Program/Verify service skeleton.

## Build-specific feature defines

Optional Bootloader features are compile-time build capabilities.
`boot_user_feature_config.h` provides default trimmed values, and each
`.projectspec` build variant explicitly enables only the capabilities required
by that build. Do not change a global default feature macro merely to enable
one build.

| Build | Purpose | AUTO_BOOT | MEMORY_READ | RUN_RAM | RESET |
|---|---|---:|---:|---:|---:|
| `bootloader_cpu01.projectspec` | CPU1 RAM development / validation | OFF | OFF | ON | OFF |
| `bootloader_cpu01_flash.projectspec` | Existing Flash baseline | ON | OFF | OFF | OFF |
| `bootloader_cpu01_flash_prod.projectspec` | CPU1 production Flash Bootloader | ON | ON | OFF | OFF |

`METADATA_SUMMARY` remains ON through its default feature value for these
builds.

Source presence does not mean that a feature exists in the generated
Bootloader image. `DeviceInfo feature_flags` must reflect the capabilities
actually compiled into that build. When adding or removing a build-specific
feature define, update this build matrix and its build-contract test in the
same change.
