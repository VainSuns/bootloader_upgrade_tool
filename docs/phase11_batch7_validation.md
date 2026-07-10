# Phase 11 Batch 7 — Advanced Page Validation

## Scope

Batch 7 replaces the `Advanced` placeholder with a static PySide6 page.

The page contains:

```text
Advanced
└─ Vertical splitter 68:32
   ├─ Diagnostics
   ├─ Flash
   ├─ Metadata
   ├─ Execution
   ├─ RAM Image
   └─ Shared Result
```

## Frozen behavior

- All target-operation buttons are visible but disabled.
- No real serial port is opened.
- No image is read or prepared.
- No Flash or metadata operation is executed.
- No reset or run command is sent.
- No CPU2 runtime backend is added.

## Flash contract

Approved action labels:

```text
Erase
Program Only
Verify Only
```

Approved erase scopes:

```text
Required App Sectors
Entire Application Region
Custom Sector Mask
```

Safety rules shown in the page:

- Sector A remains protected.
- Bootloader/reserved-sector erase requests must be rejected.
- `Verify Only` does not write `IMAGE_VALID`.
- `SERVICE_ATTACH` remains internal to operation-layer Flash and metadata calls.
- `Entire Flash` is not offered.

## Metadata contract

The page exposes three distinct disabled actions:

```text
Write IMAGE_VALID
Write BOOT_ATTEMPT
Write APP_CONFIRMED
```

`BOOT_ATTEMPT` and `APP_CONFIRMED` are explicitly described as bound to the
current image identity. Old records cannot be reused after a new image is
programmed.

## Execution and RAM contract

- `Run Flash App` is separate from metadata writes.
- `Reset Target` is a disabled placeholder until capability and policy exist.
- CPU1 and CPU2 RAM cards keep `Load / Check CRC / Run` separate.
- CPU2 RAM controls remain visible but disabled.
- `RUN_RAM / RAM_RUN` source and tests remain retained.

## Prohibited changes

Batch 7 must not modify or call:

```text
operations/**
images/**
session/**
transport/**
protocol/**
targets/**
DSP bootloader
downloaded flash_lib
linker files
Flash layout
metadata layout
CPU2 backend
W5300 backend
```

## Validation commands

```powershell
$env:QT_QPA_PLATFORM = "offscreen"

python -m pytest `
  .\tests\unit\test_gui_advanced_page.py `
  .\tests\unit\test_gui_static_layout.py `
  .\tests\unit\test_gui_view_import_boundaries.py `
  .\tests\unit\test_gui_navigation.py `
  .\tests\unit\test_gui_ribbon.py `
  .\tests\unit\test_gui_theme_contract.py `
  -q
```

Regression checks:

```powershell
python -m pytest `
  .\tests\unit\test_gui_flash_sectors.py `
  .\tests\unit\test_phase_10_8a_operations.py `
  -q

git diff --check
```

Manual review:

```powershell
python -m bootloader_upgrade_tool
```

Manual review must not connect hardware or execute an operation.
