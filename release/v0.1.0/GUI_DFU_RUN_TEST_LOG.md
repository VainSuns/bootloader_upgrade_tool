# GUI DFU + Run Test Log

## Result

PASS, reported during Phase 8.1 GUI hardware validation.

## Target

- F28377D CPU1
- SCI / RS232
- Windows GUI

## Flow

1. Launch GUI.
2. Select `.out`.
3. Convert with external `hex2000.exe`.
4. Calculate sector mask from firmware image.
5. Connect SCI / RS232.
6. Read DeviceInfo.
7. Execute DFU: Erase + Program + Verify.
8. Execute Run.
9. Confirm app starts.

## Notes

The raw GUI Save Log file was not present in the workspace when this release
artifact was generated. Replace this summary with the exported GUI log if a
byte-level release record is required.
