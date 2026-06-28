# DSP28377D Bootloader Upgrade Tool v0.1.0

## Supported Features

- Windows one-folder portable GUI build.
- Source-run GUI remains supported.
- SCI / RS232 and Simulator transports.
- CPU1 Flash app Erase, Program, Verify, DFU, and Run.
- `.out -> hex2000 -boot -a -sci8 -> FirmwareImage`.
- `hex2000.exe` resolved externally through `C200_CG_ROOT` or manual GUI path.
- Calculated-only erase sector mask; Sector A is not used by default.
- Device, firmware, memory, workflow, and protocol log views.
- Save Log from GUI.

## Hardware Requirements

- TI F28377D / F2837xD CPU1 target.
- DSP bootloader programmed and running.
- Windows PC.
- SCI / RS232 adapter.
- TI C2000 compiler with `hex2000.exe`.
- Known-good CPU1 app `.out`.

## Known Limitations

- `hex2000.exe` is not bundled.
- Packaged build is one-folder portable, not an installer.
- Reset remains hidden in GUI.
- Sector mask is calculated from firmware image ranges.
- CPU1 app only.
- No automatic recovery for interrupted Flash operations.

## Deferred Features

- W5300 / TCP.
- CPU2 upgrade.
- Metadata, upload/readback, rollback, signing, encryption, compression.
- RAM service lib dynamic loading.
- DCSM unlock.
- MSI / installer packaging.

## Test Status

- DSP Phase 5-7: passed by hardware test.
- CLI Phase 6.3 `.out -> hex2000 -> Program -> Verify`: passed by hardware test.
- CLI Phase 7.1 Run: passed by hardware test.
- GUI Phase 8.1 DFU + Run: passed by hardware test.
- Windows portable package smoke launch: passed.
- Packaged GUI DFU + Run: pending user hardware confirmation.
