# 23 Source-run Release Guide

This project currently ships as a source-run MVP. Do not build an installer for
v0.1.0.

## Version

Package version:

```text
0.1.0
```

## Install from Source

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

If activation is inconvenient:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Launch GUI

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool
```

Do not use a different global `python.exe` by accident. If the GUI only appears
with `.\.venv\Scripts\python.exe`, use that command.

## Configure hex2000

Preferred:

```powershell
$env:C2000_CG_ROOT="E:\CodeComposerStudio\CCS12.7\ccs\tools\compiler\ti-cgt-c2000_22.6.1.LTS"
```

Before the environment, normal startup reads `pc/config/gui_global_settings.json` field `hex2000.executable_path`. The Phase 11 Global Settings page is not editable yet. A non-empty invalid path is an error; when empty, `C2000_CG_ROOT` is searched at `<root>/bin/hex2000.exe` then `<root>/hex2000.exe`.

## Hardware Smoke Tests

CLI dry-run conversion:

```powershell
.\.venv\Scripts\python.exe .\tests\phase6\phase6_3_out_hex2000_workflow_test.py `
  --port COM10 `
  --out-file path\to\small_app_082400.out `
  --c2000-cg-root "E:\CodeComposerStudio\CCS12.7\ccs\tools\compiler\ti-cgt-c2000_22.6.1.LTS" `
  --dry-run
```

GUI DFU + Run:

1. Launch GUI.
2. Select `.out`.
3. Confirm entry point is at or after `0x082400`, calculated sector mask,
   and touched sectors.
4. Connect Serial.
5. Confirm DeviceInfo.
6. Click DFU.
7. Click Run.
8. Confirm the app starts.
9. Save the log.

Detailed GUI test steps are in `docs/21_gui_dfu_run_test_guide.md`.

## Release Boundary

Do not include in v0.1.0:

- PyInstaller or executable packaging.
- Protocol changes.
- DSP Flash service changes.
- W5300 / TCP.
- CPU2 upgrade.
- Metadata, rollback, signing, encryption, compression.
