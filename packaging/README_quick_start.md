# DSP28377D Bootloader Upgrade Tool - Portable Quick Start

## Run

Double-click:

```text
DSP28377D_Bootloader_Upgrade_Tool.exe
```

## hex2000

`hex2000.exe` is not bundled.

Use one of:

- `C200_CG_ROOT`
- GUI Settings -> manual `hex2000.exe` path

Example compiler root:

```text
E:\CodeComposerStudio\CCS12.7\ccs\tools\compiler\ti-cgt-c2000_22.6.1.LTS
```

## Basic GUI Flow

1. Select the app `.out`.
2. Confirm calculated sector mask does not include Sector A.
3. Select Simulator or Serial.
4. For Serial, set COM port and baud rate.
5. Connect.
6. Run DFU.
7. Run app.
8. Save Log if needed.
