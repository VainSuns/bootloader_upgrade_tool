# AGENTS.md

## GUI Rules

This directory contains the PySide6 GUI for the DSP28377D Bootloader Upgrade
Tool.

## Required Reading

Before editing GUI code, read:

- repository `AGENTS.md`;
- `docs/phase11_gui_visual_layout_contract.md`;
- `docs/phase11_gui_static_layout_skeleton.md`;
- `tests/unit/test_gui_static_layout.py`;
- `docs/phase11_gui_mvp_requirements.md`;
- `docs/phase_10_8a_operation_library_usage_example.md`;
- `docs/04_pc_gui_requirements.md`;
- `pc/src/bootloader_upgrade_tool/gui/global_settings.py`;
- `pc/src/bootloader_upgrade_tool/gui/program_controller.py`;
- `tests/unit/test_gui_flash_sectors.py`;
- `tests/unit/gui/test_program_controller.py`;
- this file.

## Frozen Layout Contract

- GUI layout is frozen. Bind logic to existing widgets only.
- Do not generate, redesign, or refactor the GUI layout.
- Do not rename existing `objectName` values.
- Layout source of truth is `docs/phase11_gui_static_layout_skeleton.md`,
  `tests/unit/test_gui_static_layout.py`,
  `pc/src/bootloader_upgrade_tool/gui/main_window.py` object names, and
  `pc/src/bootloader_upgrade_tool/gui/styles.py` constants.
- Backend semantics source of truth is `docs/phase11_gui_mvp_requirements.md`
  and `docs/04_pc_gui_requirements.md`.
- `docs/ui` legacy layout notes are historical reference only and must not
  override the frozen Ribbon layout.

Current shell object names:

```text
topRibbonShell
titleTabRow
ribbonContentRow
mainAreaSplitter
navigationPanel
pageContentStack
bottomDock
Console
```

Ribbon tabs:

```text
Session
Operate
View
Settings
```

Left navigation:

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

GUI code must follow the Phase 10.8A operation-library path:

```text
GUI widgets
  -> GUI controller / view model glue
  -> ProgramController or operation-layer wrapper
  -> operations/*
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

CPU1 Load Image / Run must reuse `ProgramController`.

Advanced DSP operations must reuse the existing Phase 10.8A operation-layer
flow.

Do not implement the GUI as:

```text
GUI button -> subprocess -> cpu1_upgrade CLI
GUI widget -> old UpgradeWorkflow
GUI widget -> old IO Device workflow
GUI widget -> direct protocol command construction
GUI widget -> direct BootProtocolClient convenience calls
GUI widget -> direct serial/socket/Simulator access
GUI widget -> duplicated image parsing / Flash / metadata / RUN sequencing
```

Old CLI, old workflow, and old GUI backend files are behavior references only.
They must not be imported or called as the Phase 11 GUI runtime path.

## Hard Constraints

- Use PySide6, not PyQt.
- DSP is always slave; PC GUI is always master.
- SCI `'A'` autobaud is connection-layer behavior, not a protocol frame.
- Use Program naming, not Download.
- Old DFU-as-normal-flow guidance is obsolete for Phase 11 GUI.
- `verify_flash_image()` only verifies data; it does not write `IMAGE_VALID`.
- `append_image_valid()` writes `IMAGE_VALID` separately.
- `run_flash_app()` only sends RUN; it does not write `BOOT_ATTEMPT`.
- `append_boot_attempt()` writes `BOOT_ATTEMPT` separately.
- `SERVICE_ATTACH` is internal operation-library behavior and must not be
  exposed as a public GUI action.
- Do not expose Reset as a main operation until deterministic policy exists and
  DeviceInfo advertises support.
- Do not copy TI trademarks, logos, icons, screenshots, or proprietary assets.

## GUI Integration Rules

- Only wire existing controls to controllers / view models.
- Keep normal workflow actions separate from Advanced/debug operations.
- `Load Image` and `Run` are the only normal CPU1 operation buttons.
- `Confirm App`, `Auto Run after Load`, and `Force Load` are options, not
  public operation buttons.
- Do not expose Erase, Program, Verify, DFU, or SERVICE_ATTACH as normal GUI
  buttons.
- Do not reimplement image parsing, Flash erase/program/verify, metadata
  writes, BOOT_ATTEMPT, APP_CONFIRMED, or RUN sequencing inside GUI widgets.
- Simulator is not a Phase 11 GUI dependency.

Retired historical rules:

```text
headerFrame / connectionStrip / bodyFrame / bottomConsole
Tools / Advanced navigation
old form-style MainWindow
legacy MainWindow attributes as a development target
```

These names may appear in historical notes only. They are not current layout
requirements.

## Styling

- Centralize visual styling in QSS:
  `pc/src/bootloader_upgrade_tool/gui/resources/styles/theme.qss`.
- Python may set object names, dynamic properties, enabled state, and text.
- Do not commit large inline `setStyleSheet()` blocks.

## Test Boundaries

GUI tests must not:

- open a real COM port;
- run real SCI autobaud;
- call subprocess or the old `cpu1_upgrade` CLI;
- erase/program/verify real Flash;
- write real metadata;
- send real RUN or reset actions;
- perform W5300/TCP or CPU2 bring-up.

Use injected fakes for session/connection factories and hardware-touching
steps.

New GUI tests should cover GUI glue only and must not duplicate existing
operation sequencing tests.

## Verification

After relevant GUI changes, run:

```powershell
python -m py_compile pc/src/bootloader_upgrade_tool/gui/*.py
pytest tests/unit/test_gui_static_layout.py
pytest tests/unit/test_gui_flash_sectors.py
pytest tests/unit/gui/test_program_controller.py
```

Run broader unit tests when the change touches firmware parsing, protocol,
operations, session, transport, or workflow behavior.
