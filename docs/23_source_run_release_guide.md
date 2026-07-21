# Source-run Guide

Source-run is one supported way to run the current GUI. Windows one-folder
portable packaging is documented separately in
[`24_windows_portable_packaging_guide.md`](24_windows_portable_packaging_guide.md).
Installer creation remains outside current work.

## Version

The package version remains:

```text
0.1.0
```

The package version and its historical release scope do not override RAC-V2,
the protocol contract, operation-library contract, or current GUI contract.

## Install and launch from source

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m bootloader_upgrade_tool
```

If activation is inconvenient:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool
```

Use the repository virtual environment rather than an unrelated global Python.

## Configure hex2000

Normal startup first reads
`pc/config/gui_global_settings.json:hex2000.executable_path`. A non-empty
invalid path is an error. When the setting is empty, lookup uses
`C2000_CG_ROOT`:

```powershell
$env:C2000_CG_ROOT="E:\CodeComposerStudio\CCS12.7\ccs\tools\compiler\ti-cgt-c2000_22.6.1.LTS"
```

The lookup checks `<root>/bin/hex2000.exe`, then `<root>/hex2000.exe`.
Global Settings > Tools can override the tool and output paths for the current
run.

## Current capability

Currently validated:

- TMS320F28377D CPU1;
- SCI/RS232;
- source-run;
- image preparation;
- persistent connection and target discovery;
- operation library;
- metadata operations;
- explicit RUN;
- simulator as a test aid.

CPU1 validation is a capability state, not a CPU1-only shared Runtime
architecture. Shared Runtime, Binding, Backend, Widget, and operation flow
remain target/profile/capability driven.

Deferred capabilities include CPU2 runtime enablement, W5300/TCP, production
deterministic Reset, security, signing/encryption, and rollback policy.

The current GUI includes metadata and Runtime V2 capabilities. This guide only
explains source execution; RAC-V2 and the operation-library contract define
workflow and admission.

## User-run hardware smoke test

The user may launch the GUI, prepare an image, connect through SCI/RS232, inspect
DeviceInfo and metadata, execute currently supported operations, and save the
log.

Only the user may perform these steps on real hardware. Codex and automated
tests must not connect a real serial port, erase/program/verify Flash, write
metadata, send RUN or Reset, or observe LEDs.
