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
