# Phase 11 GUI Visual Layout Contract

Project: `bootloader_upgrade_tool`  
Target: TMS320F28377D CPU1  
GUI stack: PySide6  
Purpose: frozen Ribbon layout contract for Phase 11 GUI integration

The Phase 11 GUI layout is frozen. Codex may bind logic to existing widgets,
but must not generate, redesign, refactor, or rename the layout.

Layout source of truth:

- `docs/phase11_gui_static_layout_skeleton.md`
- `tests/unit/test_gui_static_layout.py`
- `pc/src/bootloader_upgrade_tool/gui/main_window.py` object names
- `pc/src/bootloader_upgrade_tool/gui/styles.py` constants

Backend semantics source of truth:

- `docs/phase11_gui_mvp_requirements.md`
- `docs/04_pc_gui_requirements.md`

`docs/ui` legacy layout notes are historical reference only. They must not
override the frozen Ribbon layout.

## 1. Main Window Structure

Current `MainWindow` structure:

```text
MainWindow
├─ topRibbonShell
│  ├─ titleTabRow
│  └─ ribbonContentRow
├─ mainAreaSplitter
│  ├─ navigationPanel
│  └─ pageContentStack
└─ bottomDock
   └─ Console
```

The old `headerFrame` / `connectionStrip` / `bodyFrame` / `bottomConsole`
structure is retired historical guidance.

## 2. Ribbon

Ribbon tabs:

```text
Session
Operate
View
Settings
```

Operate tab contains:

```text
Transport block
Connect / LoadImage / Run
Status block
```

SCI transport controls contain Port and Baud. The Connect button is stateful
Connect / Disconnect. Timeout settings belong to Global Settings, not the
Operate Ribbon.

## 3. Left Navigation

Left navigation is:

```text
Program / CPU1
Program / CPU2
Settings
Memory / CPU1
Memory / CPU2
Advanced
Logs
```

CPU2 backend is reserved/disabled until explicitly implemented.

## 4. Program Pages

Program page sections:

```text
App Image
Options
Status Summary
Details / Result
```

CPU1 normal operation buttons:

```text
Load Image
Run
```

Options:

```text
Confirm App
Auto Run after Load
Force Load
```

Do not expose Erase, Program, Verify, DFU, or `SERVICE_ATTACH` as normal CPU1
workflow buttons.

## 5. Settings

Settings contains:

```text
Session Settings
Global Settings
Expander sections
```

Session Settings are current connection/session choices. Global Settings are
repo/tool paths and defaults such as timeout values, `hex2000`, flash service
paths, and temporary-file options.

## 6. Advanced

Advanced contains engineering/debug groups:

```text
Diagnostics
Flash
Metadata
Execution
RAM Image
```

Advanced DSP operations must call existing `operations/*` public APIs.
They must not call the old CLI, old workflow, old GUI backend, direct protocol
primitives, or direct serial/socket APIs.

## 7. Memory

Memory pages contain CPU1 / CPU2 memory tables:

```text
100 rows
Address + 16 word columns
```

Real memory read is deferred. The frozen layout may show static or placeholder
data only until backend support is explicitly requested.

## 8. Bottom Console

The bottom dock title is exactly:

```text
Console
```

Do not use `Console / Log` as the title.

## 9. Runtime Boundary

Allowed DSP-touching GUI path:

```text
GUI widget
  -> GUI controller / view model glue
  -> images/* for file preparation only
  -> operations/* public APIs for DSP-touching actions
  -> OperationContext / FlashOperationContext
  -> active TargetProfile / CommandSet
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

Rules:

- GUI must call `operations/*` public APIs for DSP-touching actions.
- GUI must create `OperationContext` / `FlashOperationContext` with active
  `TargetProfile`.
- Command dispatch is driven by active `TargetProfile.command_set`.
- GUI must not select command ids directly.
- GUI must not use `gui/program_controller.py` as runtime path.
- GUI must not create CPU1-specific or CPU2-specific duplicated operation flows.
- GUI must not duplicate image parsing / Flash / metadata / RUN sequencing.
- GUI must not call `cpu1_upgrade` through subprocess.
- GUI must not directly construct protocol frames.
- GUI must not directly call `BootProtocolClient` convenience methods.
- GUI must not directly open serial or socket connections from widgets.
- Old CLI, old workflow, and old GUI backend files are behavior references only.

## 10. Strict Layout Rules

- Codex may bind logic to existing `objectName` values.
- Codex may not redesign layout.
- Codex may not rename `objectName` values.
- Codex may not revive the old connection-strip layout.
- Codex may not use `docs/ui` historical layout notes as current rules.
