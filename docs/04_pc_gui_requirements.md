# 04 PC GUI Requirements

> Project: TMS320F28377D Bootloader Upgrade Tool  
> GUI framework: PySide6  
> Current baseline: Phase 10.8A PC operation library  
> Purpose: Runtime architecture and safety boundaries for the frozen Phase 11 GUI.

Current visual layout is frozen and defined by
`docs/phase11_gui_static_layout_skeleton.md`. This file constrains runtime
architecture and safety boundaries; it is not a layout-generation guide.

## 1. Technology Stack

The MVP GUI uses:

```text
Python
PySide6
Phase 10.8A PC operation library
```

The first version only needs to run from source. PyInstaller / installer packaging is not part of the MVP.

## 2. Runtime Architecture

The GUI runtime model must be:

```text
GUI widgets
  -> GUI controller / view model glue
  -> images/* for file preparation only
  -> operations/* public APIs for DSP-touching actions
  -> OperationContext / FlashOperationContext
  -> active TargetProfile / CommandSet
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

The GUI must not be implemented as:

```text
GUI button -> subprocess -> cpu1_upgrade CLI command
GUI widget -> direct protocol primitive calls
GUI widget -> direct pySerial/socket calls
GUI widget -> duplicated image parsing / Flash / metadata / RUN sequencing
```

All DSP-touching actions must go through `operations/*` public APIs. GUI glue
may use `images/*` only for PC-side file preparation and identity comparison.
The GUI must create `OperationContext` / `FlashOperationContext` with the
active `TargetProfile`. Command dispatch is driven by active
`TargetProfile.command_set`; operations use `ctx.target.command_set` and
`require_command()` to resolve command ids.

The GUI must not import or call `gui/program_controller.py` as the Phase 11.1
runtime path. The GUI must not select command ids directly. The GUI must not
create CPU1-specific or CPU2-specific duplicated operation flows. The GUI must
not reimplement image parsing, Flash, metadata, or RUN sequencing.

The old `cpu1_upgrade` CLI, old `UpgradeWorkflow`, and old GUI backend files
remain behavior/regression references only. They must not be used as the Phase
11 GUI runtime path.

## 3. Persistent Connection

The GUI Connect action creates a persistent `UpgradeSession`.

SCI Connect behavior:

```text
SerialTransport.open()
  -> pySerial open
  -> SCI autobaud with ASCII 'A'
  -> wait for DSP echo 'A'
  -> connected session ready
```

After Connect succeeds:

```text
Load Image, Run, Advanced, and Logs/Results operations reuse the connected session.
Subsequent operations do not repeat autobaud.
Connect button toggles to Disconnect.
```

Operate Ribbon / Transport block shows only common SCI fields:

```text
Port
Baud
Connect / Disconnect
Status
```

The Connect button is stateful Connect / Disconnect.

The following settings belong in Global Settings, not in the Operate Ribbon:

```text
TX Timeout ms
RX Timeout ms
Autobaud Timeout ms
```

## 4. Global Settings

Until the final GUI installation/resource layout is confirmed, the GUI uses a user-editable global configuration file.

Recommended development path:

```text
pc/config/gui_global_settings.json
```

Repository template:

```text
pc/config/gui_global_settings.example.json
```

Global Settings include:

```text
hex2000 executable path
flash_service_lib image path
flash_service_lib map path
descriptor symbol
SCI8 temporary directory
keep generated SCI8 TXT
TX Timeout ms
RX Timeout ms
Autobaud Timeout ms
```

`flash_service_lib` paths may come from the global config file, but descriptor address must still be parsed from map/symbol data. The GUI must not hardcode descriptor address.

## 5. CPU1 Program Page

CPU1 is the only enabled program target in the MVP.

CPU1 page main buttons:

```text
Load Image
Run
```

CPU1 page options:

```text
Force Load
Auto Run after Load
Confirm App
```

Semantics:

```text
Load Image = write image only
Run = append BOOT_ATTEMPT if needed, then RUN
Confirm App = Run option, not a standalone button
Force Load = force image rewrite even when metadata matches
Auto Run after Load = after Load Image succeeds, run the same Run sequence
```

CPU2 page is disabled in the MVP.

## 6. Load Image Flow

Load Image must not automatically run the App.

Load Image sequence:

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

If current metadata already matches the selected App image:

```text
Force Load off -> skip Load Image and guide user to enable Force Load if needed
Force Load on  -> erase/program/verify/append IMAGE_VALID anyway
```

Important Phase 10.8A operation-library semantics:

```text
verify_flash_image() verifies only.
append_image_valid() writes IMAGE_VALID separately.
Load Image does not write BOOT_ATTEMPT.
Load Image does not write APP_CONFIRMED.
Load Image does not RUN.
```

## 7. Run Flow

Run sequence without Confirm App:

```text
Read Metadata
Validate current IMAGE_VALID
Append BOOT_ATTEMPT if needed
Run Flash App
```

Run sequence with Confirm App enabled:

```text
Read Metadata
Validate current IMAGE_VALID
Append BOOT_ATTEMPT if needed
Append APP_CONFIRMED if needed
Run Flash App
```

`APP_CONFIRMED` must be written before RUN because after RUN the GUI cannot assume bootloader communication is still available.

## 8. Advanced Page

Advanced page should use tabs:

```text
Status
Flash Operations
Metadata Operations
Execution
RAM
Raw Results
```

`SERVICE_ATTACH` must not be exposed as a GUI button, including in Advanced. Service attach/reuse is an internal detail of flash/metadata operations and may appear only in OperationResult details.

Reset may be exposed in Advanced, but must be marked:

```text
Experimental / Requires DSP support
```

If unsupported, it must be shown as a target capability/workflow issue, not as a GUI crash.

## 9. OperationResult and Logs

The GUI should render `OperationResult` as:

```text
Normal page:
  user-readable status, message, suggestion

Advanced / Logs:
  summary
  details
  service
  warning
  error.code
  error.stage
  error.message
  JSON export via operation_result_to_dict()
```

Business states such as already-existing metadata records should be displayed as workflow guidance rather than fatal errors.

## 10. Progress and Cancel

Long operations must not block the GUI thread.

Recommended model:

```text
QThread / worker object
progress signal
result signal
error signal
cancel request flag
```

Cancel behavior:

```text
cooperative cancel only
allow stop at next chunk or next operation step
no forced thread termination
Run stage is not cancelable
```

## 11. Safety and Forbidden Actions

Codex / automated tests must not:

```text
open a real COM port
perform real autobaud
erase real Flash
program real Flash
verify real Flash
write real metadata
send real RUN
reset DSP
perform real W5300 communication
perform CPU2 bring-up
```

Phase 11 GUI work must not modify:

```text
DSP bootloader code
flash_service_lib DSP code
linker cmd
Flash sector layout
protocol payload
confirmed-only boot policy
F2837xD low-level initialization
```

GUI glue tests should cover widget/controller integration only. They should not
copy existing operation sequencing tests.

## 12. Related Documents

Primary Phase 11 requirement document:

```text
docs/phase11_gui_mvp_requirements.md
```

Phase 10.8A operation-library document:

```text
docs/phase_10_8a_pc_operation_library.md
```
