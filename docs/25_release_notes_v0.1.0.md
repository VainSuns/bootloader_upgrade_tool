# Release Notes

Release version: v0.1.0

## Supported features

- Windows portable GUI
- SCI / RS232
- Simulator
- F28377D CPU1 Flash app
- `.out -> hex2000 -> sci8`
- Erase / Program / Verify
- GUI DFU
- Run App
- Save Log

## Hardware requirements

- F28377D CPU1
- SCI-A / RS232
- GPIO64 RX / GPIO65 TX
- known-good bootloader kernel

## PC requirements

- Windows
- packaged portable folder
- external `hex2000.exe`

## Known limitations

- Reset hidden
- RAM_LOAD hidden
- no W5300
- no CPU2
- no metadata / rollback
- no signing / encryption
- no installer

## Validation status

- CLI Phase 6.3 PASS
- CLI Phase 7.1 PASS
- GUI DFU + Run PASS
- packaged exe smoke test PASS
