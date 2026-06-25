# Phase 4 user integration checklist

The generated algorithm is hardware-independent. Complete and review these
items in the user's CCS project before target testing.

## Required for DeviceInfo target integration

- [ ] Provide product-owned system initialization before `BootAlgorithm_Run`.
- [ ] Configure SCI pins and peripheral clocks using the product BSP.
- [ ] Implement ASCII `A` autobaud in `BootIoOps.connect_master`.
- [ ] Implement blocking 16-bit word receive/send with low wire byte first.
- [ ] Implement the connection timeout locally; do not add a protocol status.
- [ ] Fill complete PARTIDL/PARTIDH/REVID/UID identity in `BootDeviceInfo` and
      keep its v1 REVID/UID_UNIQUE export consistent with the PC.
- [ ] Reserve protocol RX state/buffers in the reviewed linker placement.
- [ ] Call `BootAlgorithm_Init`, then `BootAlgorithm_Run` or repeated
      `BootAlgorithm_ProcessOne` from the product outer loop.
- [ ] Verify Ping, GetDeviceInfo, GetProtocolInfo, bad CRC resync, and sequence
      echo on the real SCI link.

## Required later for Erase/Program/Verify

- [ ] Implement and review `BootFlash_*` outside the algorithm core.
- [ ] Make the complete Flash call chain, busy wait, constants, and error path RAM-safe.
- [ ] Configure F28377D Flash wait states and active bank in product code.
- [ ] Handle pump semaphore and DCSM policy in product code where applicable.
- [ ] Preserve API status, FMSTAT, failing address, and BlankCheck/Verify detail.
- [ ] Reject protected/out-of-range addresses and repeated programming before erase.
- [ ] Confirm sector-mask ordering exactly matches `device_info.json.flash_sectors`.

The low-level items above intentionally remain user-owned and must not be
implemented by Codex without an explicit change to the architecture constraints.
