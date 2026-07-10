# AGENTS.md

## GUI Rules

This directory contains the PySide6 GUI for the TMS320F28377D Bootloader Upgrade Tool.

## Required Reading

Before editing GUI code, read:

- repository `AGENTS.md`;
- `docs/phase11_gui_layout_v1_contract.md`;
- `docs/phase11_gui_mvp_requirements.md`;
- `docs/phase_10_8a_operation_library_usage_example.md`;
- `docs/phase_10_8a_pc_operation_library.md`;
- `docs/04_pc_gui_requirements.md`;
- `pc/src/bootloader_upgrade_tool/gui/global_settings.py`;
- `tests/unit/test_gui_flash_sectors.py`;
- `tests/unit/test_phase_10_8a_operations.py`;
- `pc/src/bootloader_upgrade_tool/operations/` public APIs;
- `pc/src/bootloader_upgrade_tool/targets/` TargetProfile / CommandSet;
- `pc/src/bootloader_upgrade_tool/images/` preparation APIs;
- this file.

Legacy migration references:

- `docs/phase11_gui_static_layout_skeleton.md`;
- the pre-migration `tests/unit/test_gui_static_layout.py` assertions;
- the former single-file `main_window.py` implementation;
- the former `styles.py::APP_QSS` theme.

## Approved Layout Migration

The old single-file GUI is an implementation baseline, not the final layout contract. The GUI must be migrated to:

```text
docs/phase11_gui_layout_v1_contract.md
```

The layout design is frozen at V1.0, but migration from the former skeleton is explicitly allowed.

Allowed:

- split `main_window.py` into the approved pages/widgets modules;
- replace `APP_QSS` with `theme.py -> resources/styles/theme.qss`;
- add `layout_metrics.py`, `theme_tokens.py`, `ui_state.py`, and `icon_manager.py`;
- migrate object names according to the contract's explicit mapping;
- add the approved workspace, page, Advanced, Memory, Logs, and Console splitters;
- update layout tests incrementally with each migrated component.

Not allowed:

- redesigning beyond the approved contract;
- changing Ribbon tab order or navigation hierarchy;
- changing Session Ribbon or Operate CPU-status semantics;
- inventing additional pages or normal operation buttons;
- deleting CPU2/TCP review placeholders;
- connecting real hardware during static-layout implementation.

## Frozen V1.0 Shell

Core structure:

```text
bootloaderMainWindow
└─ mainRoot
   ├─ topRibbonShell
   │  ├─ titleTabRow
   │  │  └─ ribbonTabBar
   │  └─ ribbonContentRow
   │     └─ ribbonPageStack
   └─ workspaceVerticalSplitter
      ├─ mainAreaSplitter
      │  ├─ navigationPanel
      │  │  └─ navigationTree
      │  └─ pageContentHost
      │     └─ pageContentStack
      └─ bottomDock
         ├─ bottomDockHeader
         └─ bottomConsoleBody
            └─ consoleOutput
```

Ribbon tabs remain exactly:

```text
Session
Operate
View
Settings
```

Navigation remains exactly:

```text
Program / CPU1
Program / CPU2
Settings
Memory / CPU1
Memory / CPU2
Advanced
Logs
```

## Phase 11 Runtime Path

```text
GUI widgets
  -> GUI controller / view-model glue
  -> images/* for file preparation only
  -> operations/* public APIs for DSP-touching actions
  -> OperationContext / FlashOperationContext
  -> active TargetProfile / CommandSet
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

All DSP-touching GUI actions must call `operations/*` public APIs. GUI widgets must not call the old CLI, old workflow, direct protocol primitives, command IDs, serial/socket APIs, or duplicate image/Flash/metadata/RUN sequencing.

Do not use `gui/program_controller.py` as the Phase 11 runtime path. Historical compatibility tests may remain, but they are not the sequencing source of truth.

## Hard Constraints

- Use PySide6, not PyQt.
- DSP is slave; PC GUI is master.
- SCI `'A'` autobaud is connection-layer behavior, not a protocol frame.
- Use Program naming, not Download.
- Normal CPU1 operation buttons remain Load Image and Run.
- Confirm App, Auto Run after Load, and Force Load are options.
- SERVICE_ATTACH is never a public GUI operation.
- Verify does not write IMAGE_VALID.
- RUN does not write BOOT_ATTEMPT.
- Bootloader reads metadata only; downloaded flash_lib performs metadata writes.
- Do not copy TI trademarks, logos, icons, screenshots, or proprietary assets.

## View-Layer Import Boundary

During static layout implementation, `gui/pages/**`, `gui/widgets/**`, `main_window.py`, and preview modules may import only Python, PySide6, and GUI support modules. They must not import:

```text
operations
images
session
transport
protocol
targets
pyserial
cpu1_upgrade
```

Runtime integration modules will be introduced only after a separate boundary review.

## Styling

- The sole application theme is `resources/styles/theme.qss`.
- Colors and typography tokens live in `theme_tokens.py`.
- Dimensions and splitter metrics live in `layout_metrics.py`.
- Python controls layout, objectName, dynamic properties, visibility, enabled state, and icon size.
- QSS controls colors, typography, borders, radii, hover, pressed, focus, disabled, checked, and semantic states.
- Do not add large inline `setStyleSheet()` blocks.
- Do not reference SVG paths directly from page code; use semantic icon keys through `IconManager`.

## Test Boundaries

GUI tests must not:

- open a real COM port;
- perform real SCI autobaud;
- call subprocess or `cpu1_upgrade`;
- erase/program/verify real Flash;
- write real metadata;
- send real RUN or reset commands;
- perform W5300/TCP or CPU2 bring-up.

Use static preview data and injected fakes. New GUI tests cover GUI structure and glue only and must not duplicate operation sequencing tests.

## Verification

Run the relevant subset after each migration batch:

```powershell
python -m py_compile pc/src/bootloader_upgrade_tool/gui/*.py
pytest tests/unit/test_gui_static_layout.py
pytest tests/unit/test_gui_flash_sectors.py
pytest tests/unit/test_phase_10_8a_operations.py
```

Run broader tests only when the change actually touches backend modules.
