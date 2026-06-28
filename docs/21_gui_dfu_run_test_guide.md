# 21 GUI DFU and Run Hardware Test Guide

## Scope

This guide validates the PC GUI path after the Phase 6 / Phase 7 command-line
flows have already passed.

Do not use this guide to change protocol bytes, DSP code, Flash service code,
or Phase 6 / Phase 7 scripts.

## Prerequisites

- DSP bootloader is programmed and running on F28377D CPU1.
- RS232 adapter is connected, for example `COM10 @ 9600`.
- Python environment is installed with the project in editable mode.
- `hex2000.exe` is available through `C200_CG_ROOT` or the GUI manual path.
- A known-good CPU1 app `.out` exists, for example:

```text
tests\phase6\led_blinky.out
```

## Launch

From the repository root:

```bat
".\.venv\Scripts\python.exe" -m bootloader_upgrade_tool
```

## Test Steps

1. Select the `.out` file.
2. Confirm the firmware summary shows:
   - entry point inside app Flash;
   - nonzero block count;
   - calculated sector mask;
   - no Sector A in the mask.
3. Select Serial transport.
4. Set port and baud rate, for example:

```text
COM10
9600
```

5. Click Connect, then reset/restart the DSP bootloader if needed for autobaud.
6. Click Get Device Info.
7. Confirm the device summary shows:
   - `Device ID`;
   - `CPU ID`;
   - `Protocol Version`;
   - decoded `Feature Flags`;
   - `Max Payload Words`;
   - `Max Data Words`;
   - `Boot Mode`;
   - `Kernel Layout`;
   - `Revision ID`;
   - `UID Unique`.
8. Confirm the GUI enables only operations advertised by `Feature Flags`.
9. Click DFU and wait for Erase, Program, and Verify to complete.
10. Click Run.
11. Confirm the app starts, for example LED blinking.
12. Use Save Log to export the GUI console log.

## Expected Result

```text
Firmware loaded: yes
Device connected: yes
Sector mask valid: yes
Supported features: ERASE, PROGRAM, VERIFY, RUN
Last operation result: Run: OK
```

The Reset operation must remain hidden. The sector mask must remain calculated
from the firmware image; do not enter or default to Sector A.
