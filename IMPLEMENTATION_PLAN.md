# Implementation Status: Phases 0-5

This file summarizes the implemented milestones from `docs/11_codex_task_list.md`.
It does not replace the project requirements or protocol specification.

## Phase 0: Repository baseline — complete

- Repository structure for `pc/`, `dsp/`, `tools/`, `examples/`, and `tests/`.
- Project documentation and `AGENTS.md` development constraints.
- Python 3.12 source-layout project with PySide6 and pytest configuration.

## Phase 1: Firmware and linker parsing — complete

- TI linker `.cmd` `MEMORY` parsing and `device_info.json` generation.
- Manual-path-first `hex2000` lookup with `C200_CG_ROOT` fallback.
- `hex2000 -boot -a -sci8` invocation and SCI8 boot-table parsing.
- Immutable `FirmwareImage`, block, checksum, and address-range models.

Real `hex2000` output remains to be validated with the user's installed C2000
toolchain.

## Phase 2: PC protocol core — complete

- Frozen protocol constants and CRC-16/CCITT-FALSE over little-endian words.
- Frame encode/decode, sequence handling, and bounded resynchronization.
- `DeviceInfo` and `ErrorDetail` payload models.
- Eight-word validation and `0xFFFF` PC-side padding helpers.
- `DeviceInfo` enforces `max_data_words + 5 <= max_payload_words`.

## Phase 3: PC GUI, IO, and Simulator — complete skeleton

- PySide6 source-run GUI with the current button-based operation flow.
- Read-only firmware and connected-device summaries.
- `PcIoDevice`, `SerialIoDevice`, and `SimulatorIoDevice`.
- SCI `A` handshake boundary isolated in the serial adapter.
- Protocol client, Erase/Program/Verify/DFU/Run/Reset workflow, and timeout probe.
- `SimulatorCore` with sparse Flash, sessions, validation, and fault injection.

GUI visual redesign and persistent manual `hex2000` path storage remain deferred.

## Phase 4: DSP upper-layer skeleton — complete

- `BootIoOps`, connection delegation, CRC, sliding word resync, and frame responses.
- Ping, GetDeviceInfo, GetProtocolInfo, and GetLastError dispatch.
- Complete protocol status and feature constants without Phase 5 behavior.
- Internal `BootDeviceIdentity`; GetDeviceInfo v1 remains fixed at 16 words and
  exports only `revision_id` and `uid_unique` from the full identity.
- `BootFlash_*` / `BootRam_*` user-port headers and guarded user templates.
- Host-side C tests built with warnings as errors.

## Phase 5: RAM Flash service command flow — implemented skeleton

- PC normal transactions use byte-level response magic resynchronization.
- Operation-specific timeouts cover Erase, Program, Verify, Run, and Reset.
- Flash-resident DSP core owns IO, protocol receive/send, core commands,
  RamLoadBegin/Data/End skeleton, service forwarding, and pending Run entry.
- RAM-resident Flash service lib owns Erase/Program/Verify command validation,
  transfer sessions, Flash error mapping, and calls to user-owned `BootFlash_*`.
- `BootServiceApi` / `BootCoreServices` provide the core-to-lib ABI; the lib
  never owns protocol transport or duplicates the receive loop.
- Flash failures populate `BootErrorDetail`; PC workflows query GetLastError
  after operation-level protocol failures.
- Run and Reset return a small `BootAlgorithmAction` after the OK response.
  `BootAlgorithm_GetPendingEntryPoint()` exposes the validated Run entry point;
  the product outer layer remains responsible for the real jump/reset.

## Remaining before user hardware porting

- Confirm product `max_payload_words` / `max_data_words` values.
- Confirm linker-derived application ranges and 13-sector mask ordering.
- Validate SCI8 parsing against real `hex2000` output.
- Complete CCS build integration and real Erase/Program/Verify/Run testing.
- Define the production RAM service image load/activation policy.
- Generate and link the RAM service symbol library without storing service code
  in bootloader Flash.

## User-owned hardware responsibilities

- System clock, PLL, watchdog, pinmux, SCI registers, and autobaud internals.
- Flash wait states, raw TI F021 calls, pump semaphore, DCSM/FLSEM, and linker placement.
- Populate complete PARTID/REVID/UID identity in `BootUser_CreateDeviceInfo`.
- Real App jump and device reset handling for returned `BootAlgorithmAction`.
- Real RAM service linker command files and service entry placement.

DSP-facing APIs return no more than 32 bits. Larger results and structures use
caller-provided output pointers.
