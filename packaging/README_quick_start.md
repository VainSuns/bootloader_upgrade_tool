# DSP28377D Bootloader Upgrade Tool - Portable Quick Start

## Run

Double-click:

```text
DSP28377D_Bootloader_Upgrade_Tool.exe
```

## hex2000

`hex2000.exe` is not bundled.

Resolution order:

1. `pc/config/gui_global_settings.json` field `hex2000.executable_path`, read at normal startup.
2. `C2000_CG_ROOT`, using `<root>/bin/hex2000.exe` then `<root>/hex2000.exe`.

Global Settings > Tools allows editing the hex2000 path and Output directory for the current run; Output directory defaults to the user cache directory. A non-empty invalid configured path is an error; the environment is used only when the configured path is empty.

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
