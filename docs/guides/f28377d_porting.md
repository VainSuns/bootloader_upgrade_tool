# TMS320F28377D Porting Guide

This guide defines the user-maintained device boundary for adapting the bootloader and downloaded Flash Service to a TMS320F28377D board. Product behavior and wire formats remain authoritative in [`../contracts/`](../contracts/).

## User-owned hardware integration

The user port owns system initialization, clock/PLL setup, Flash wait states, SCI or future transport initialization, SCI autobaud, CPU timers/ticks, Flash pump semaphore, DCSM/FLSEM policy, raw TI F021 calls, application jump, reset, linker placement, and RAM-execution configuration. Project-specific device-support replacements belong under the owning `bootloader_user` layer, use `BootUser_` symbols, and retain upstream license attribution.

Typical port modules provide the IO, Flash, RAM, delay, device-information, and action interfaces consumed by the algorithm core. Hardware register access and device-specific branch/reset mechanisms stay in this layer.

## Device information and target profile

The `device_info` tool parses the linker's `MEMORY` declaration and generates target data used by `TargetProfile`. Its data includes device/CPU identity, memory regions, Flash sectors, allowed address ranges, the default erase region, and valid entry-point ranges.

Flash-sector order is significant: `sector_mask` bit *n* maps to `flash_sectors[n]`. CPU1 and CPU2 require independently generated device/profile data; CPU1 values must not be reused as CPU2 defaults.

The linker `MEMORY` map and allocation map are also inputs to the generated RAM writable limits. Bootloader-owned RAM must be represented accurately, with reserved areas and errata tails excluded. Generated range ends are exclusive C28x 16-bit word addresses.

## F021 and Flash rules

The F2837xD port normally uses `F021_F2837xD_C28x.h` and `Fapi_FlashBank0`. Initialization, active-bank selection, erase/program commands, FSM-ready polling, FMSTAT inspection, blank check, verify, and pipeline flush belong in the low-level wrapper.

During erase or program, the wrapper, its caller chain, wait loop, constants, and error path must execute safely from RAM rather than fetching from the Flash bank being modified.

Erase succeeds only after the API command succeeds, the FSM becomes ready, FMSTAT is clear, and blank check succeeds. Program uses AutoECC generation, checks the API and FMSTAT, and verifies the written data. Verify preserves the first failing address and status.

C28x uses four 16-bit words per 64-bit unit and eight words per 128-bit unit. Flash Program/Verify blocks are eight-word aligned; missing PC image data is padded with `0xFFFF`. Do not program part of an AutoECC 64-bit block and complete it later, or reprogram that block before erase. RAM-load data does not use the Flash alignment rule.

Low-level failures should return a small result code and fill an error-detail output structure containing the operation, address, word length, API status, FMSTAT, and any relevant extra value. Upper layers map this information to the protocol error detail; they do not call raw F021 APIs.

## Linker and control-transfer responsibilities

The Flash-resident core and downloaded service are separately linked artifacts. The core must not statically link F021 or the service library. The service descriptor, executable sections, mutable sections, stack, and RAM writable regions must agree with the linker map and the [Flash Service contract](../contracts/flash_service.md).

Application jump and reset are user-port actions requested by the algorithm only after it has sent the protocol response. The port must validate the entry point against the application Flash range immediately before the device-specific branch. Production Reset remains unavailable until a deterministic reset implementation is provided and advertised.
