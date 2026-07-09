# Phase 11 GUI MVP Requirements

## 1. Scope

Phase 11 GUI MVP provides a PySide6 engineering GUI for the TMS320F28377D bootloader upgrade tool.

The GUI backend is based on Phase 10.8A PC operation library.

This file remains the backend semantics contract. The concrete visual layout is
frozen and is defined by `docs/phase11_gui_static_layout_skeleton.md` and
`tests/unit/test_gui_static_layout.py`. Codex must not generate or redesign the
GUI layout; Phase 11.1 work is GUI integration on the frozen Ribbon layout.

Runtime model:

```text
GUI widgets
  -> GUI controller / view model glue
  -> ProgramController or operation-layer wrapper
  -> operations/*
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

The GUI must not use:

```text
GUI -> subprocess -> cpu1_upgrade CLI
GUI widget -> direct protocol calls
GUI widget -> direct serial operations
GUI widget -> duplicated image parsing / Flash / metadata / RUN sequencing
```

CPU1 Load Image / Run must use `ProgramController`. Advanced DSP operations
must use the existing Phase 10.8A operation-layer flow. Old CLI, old workflow,
and old GUI backend files are behavior references only and must not be used as
the runtime path.

---

## 2. GUI Structure

Main navigation:

```text
Program
  ├─ CPU1
  └─ CPU2 (disabled)
Settings
Memory
  ├─ CPU1
  └─ CPU2
Advanced
Logs / Results
```

CPU2 is disabled in MVP.

CPU1 is the only executable upgrade target.

---

## 3. Connection

Connection is persistent.

Connect:

```text
Create SerialTransport
Create UpgradeSession
Connect transport
Keep session/context
```

After Connect succeeds:

```text
Load Image
Run
Advanced operations
```

all reuse the same session.

Operate Ribbon / Transport block only shows:

```text
Port
Baud
Connect / Disconnect
Status
```

Timeout parameters belong to Global Settings.

---

## 4. Global Configuration

Before final GUI packaging layout is confirmed, use:

```text
pc/config/gui_global_settings.json
```

Template:

```text
pc/config/gui_global_settings.example.json
```

Global configuration contains:

```text
hex2000 path
flash_service_lib image path
flash_service_lib map path
descriptor symbol
SCI8 temporary directory
connection timeout
```

Session does not store these program-level paths.

Session Settings are current connection/session choices in the frozen Ribbon
GUI. Global Settings are persistent defaults and tool paths.

---

## 5. CPU1 Page

Main buttons:

```text
Load Image
Run
```

Options:

```text
Force Load
Auto Run after Load
Confirm App
```

Meaning:

```text
Load Image:
  write image only

Run:
  prepare BOOT_ATTEMPT if required and start application

Confirm App:
  Run option, not a standalone button
```

---

## 6. Load Image Flow

Load Image does not automatically run App.

Sequence:

```text
Validate Inputs
Prepare App Image
Prepare Flash Service
Read Metadata
Compare Image Identity
Erase Flash Image Area
Program Flash Image
Verify Flash Image
Append IMAGE_VALID
Finish
```

Same image:

```text
same IMAGE_VALID + Force Load disabled:
    skip

Force Load enabled:
    erase/program/verify/write IMAGE_VALID
```

Important semantics:

```text
verify_flash_image() only verifies.
append_image_valid() writes IMAGE_VALID.
Load Image does not write BOOT_ATTEMPT.
Load Image does not write APP_CONFIRMED.
Load Image does not RUN.
```

---

## 7. Run Flow

Run button:

```text
Read Metadata
Check IMAGE_VALID
Append BOOT_ATTEMPT if required
Optional APP_CONFIRMED if Confirm App enabled
Run Flash App
```

APP_CONFIRMED must be written before RUN because communication after RUN cannot be guaranteed.

---

## 8. Phase 10.8A Operation Usage Example

Image parsing, flash service parsing, Flash operations, metadata writes, and
Run operations already have operation-library foundations. GUI code must reuse
those foundations instead of duplicating sequencing inside widgets.

### Persistent session

```python
transport = SerialTransport(
    SerialTransportConfig(
        port='COM3',
        baudrate=9600,
        tx_timeout_ms=1000,
        rx_timeout_ms=1000,
        autobaud_timeout_ms=5000,
    )
)

session = UpgradeSession(UpgradeSessionConfig(transport))
session.connect()

ctx = OperationContext(
    session=session,
    target=CPU1_PROFILE,
)
```

### Image preparation

```python
app = prepare_flash_app_image(
    app_image_path='app_cpu1.out',
    target=CPU1_PROFILE,
)

service = prepare_service_image(
    service_image_path='flash_service_lib.out',
    service_map_path='flash_service_lib.map',
    target=CPU1_PROFILE,
    descriptor_symbol='g_boot_flash_service_descriptor',
)
```

Requirements:

```text
descriptor address must come from map/symbol parsing.
GUI must not hardcode descriptor address.
```

### Load Image

```text
erase_flash_image_area
program_flash_image
verify_flash_image
append_image_valid
```

### Run

```text
append_boot_attempt
run_flash_app
```

### Confirm App option

```text
append_boot_attempt
append_app_confirmed
run_flash_app
```

---

## 9. Advanced

Tabs:

```text
Status
Flash Operations
Metadata Operations
Execution
RAM
Raw Results
```

SERVICE_ATTACH is not a user operation.

It may only appear in OperationResult details.

Reset may be exposed as:

```text
Experimental / Requires DSP support
```

---

## 10. Result and Progress

Normal UI shows:

```text
status
message
suggestion
```

Advanced shows:

```text
summary
details
service
warning
error
JSON export
```

Long operations use worker thread and progress signals.

Cancel:

```text
cooperative cancel only
stop at operation/chunk boundary
no forced thread termination
Run stage cannot cancel
```

---

## 11. Forbidden Changes

Phase 11 GUI must not modify:

```text
DSP bootloader
flash_service_lib DSP code
linker cmd
Flash layout
protocol payload
confirmed-only boot policy
CPU2 backend
W5300 backend
```

Automated tests must not execute real:

```text
COM connection
autobaud
Flash erase/program/verify
metadata write
RUN
DSP reset
W5300 communication
CPU2 bring-up
```

New GUI tests should cover GUI glue only and must not duplicate existing
operation sequencing tests.

Future only unless explicitly requested:

```text
W5300/TCP
CPU2 backend
packaging
```
