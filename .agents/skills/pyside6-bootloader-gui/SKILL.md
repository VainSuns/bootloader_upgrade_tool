---
name: pyside6-bootloader-gui
description: Phase 11 PySide6 GUI layout implementation and integration rules for the TMS320F28377D Bootloader Upgrade Tool.
---

# Phase 11 PySide6 GUI Rules

Use this Skill when a task touches this repository's PySide6 GUI, GUI layout, QSS, icons, console, screenshots, GUI wiring, or GUI tests.

The approved V1.0 design is frozen. Migration from the former single-file static skeleton to that approved design is explicitly allowed; redesign beyond the approved contract is not allowed.

## Required Reading

Before changing GUI code or guidance, read:

- `AGENTS.md`
- `pc/src/bootloader_upgrade_tool/gui/AGENTS.md`
- `docs/phase11_gui_layout_v1_contract.md`
- `docs/phase11_gui_mvp_requirements.md`
- `docs/04_pc_gui_requirements.md`
- `docs/phase_10_8a_operation_library_usage_example.md`
- `docs/phase_10_8a_pc_operation_library.md`
- `tests/unit/test_phase_10_8a_operations.py`

The former `docs/phase11_gui_static_layout_skeleton.md` and pre-migration GUI source/tests are legacy migration references only.

## Approved Layout Migration

Allowed:

- implement the approved modular file structure;
- split the old `main_window.py` into documented pages and widgets;
- migrate from `styles.py::APP_QSS` to the approved tokenized theme pipeline;
- migrate object names only according to the V1.0 mapping;
- add the approved splitters and shared panels;
- update static layout tests incrementally.

Not allowed:

- changing the approved Ribbon or navigation structure;
- inventing additional pages or normal workflows;
- changing operation or protocol semantics;
- deleting CPU2 or TCP review placeholders;
- performing real hardware operations.

## Operation Flow Rules

All DSP-touching GUI operations use:

```text
GUI widget
  -> GUI controller / view-model glue
  -> images/* for PC-side file preparation only
  -> operations/* public APIs
  -> OperationContext / FlashOperationContext
  -> active TargetProfile / CommandSet
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

- The GUI never selects command IDs directly.
- Operations resolve commands through `ctx.target.command_set` and `require_command()`.
- Do not use `gui/program_controller.py` as the Phase 11 runtime path.
- Do not create duplicated CPU1/CPU2 operation flows.
- Do not call `cpu1_upgrade` through subprocess.
- Do not directly use pySerial, sockets, Simulator internals, protocol primitives, or BootProtocolClient convenience methods from widgets.
- Do not reimplement image parsing, Flash erase/program/verify, metadata writes, BOOT_ATTEMPT, APP_CONFIRMED, or RUN sequencing.

## Hard Rules

- Use PySide6, not PyQt.
- Default target is TMS320F28377D.
- DSP is slave; PC GUI is master.
- SCI `'A'` autobaud is connection-layer behavior.
- Use Program naming, not Download.
- SERVICE_ATTACH is internal and not a public GUI action.
- Verify does not write IMAGE_VALID.
- RUN does not write BOOT_ATTEMPT.
- Bootloader reads metadata only.
- Do not modify low-level DSP initialization or linker configuration during GUI tasks.
- Do not copy TI trademarks, logos, screenshots, or proprietary assets.

## Styling and Icons

- Main theme: `pc/src/bootloader_upgrade_tool/gui/resources/styles/theme.qss`.
- Theme tokens: `theme_tokens.py`.
- Layout metrics: `layout_metrics.py`.
- Dynamic properties: `uiRole`, `variant`, `state`, `level`, `scope`.
- Icons are loaded by semantic key through `IconManager`.
- Do not add large inline style sheets or direct SVG paths in pages.
- Console text coloring is implemented with `QSyntaxHighlighter`, not HTML.

## Testing Rules

- GUI tests use static preview data and injected fakes.
- Do not duplicate operation sequencing tests.
- Tests must not open COM ports, perform autobaud, call subprocess, or execute real Flash, metadata, RUN, reset, W5300, or CPU2 operations.

## Verification

```powershell
pytest tests/unit/test_gui_static_layout.py
pytest tests/unit/test_gui_flash_sectors.py
pytest tests/unit/test_phase_10_8a_operations.py
```

Run additional GUI contract tests as they are introduced by each migration batch.
