---
name: pyside6-bootloader-gui
description: Phase 11 PySide6 GUI Integration Rules for the DSP28377D Bootloader Upgrade Tool.
---

# Phase 11 PySide6 GUI Integration Rules

Use this Skill when a task touches this repository's PySide6 GUI, GUI wiring,
QSS, console, screenshot acceptance, or GUI tests.

This Skill is not a layout-generation Skill. The Phase 11 GUI layout is frozen.

## Required Reading

Before changing GUI code or GUI guidance, read:

- `AGENTS.md`
- `pc/src/bootloader_upgrade_tool/gui/AGENTS.md`
- `docs/phase11_gui_static_layout_skeleton.md`
- `tests/unit/test_gui_static_layout.py`
- `docs/phase11_gui_mvp_requirements.md`
- `docs/04_pc_gui_requirements.md`
- `docs/phase_10_8a_operation_library_usage_example.md`
- `pc/src/bootloader_upgrade_tool/gui/program_controller.py`

## Frozen Layout Rules

- GUI layout is frozen.
- Do not generate, redesign, or refactor the GUI layout.
- Do not rename existing `objectName` values.
- Bind logic to existing widgets only.
- Layout source of truth is `docs/phase11_gui_static_layout_skeleton.md`,
  `tests/unit/test_gui_static_layout.py`,
  `pc/src/bootloader_upgrade_tool/gui/main_window.py` object names, and
  `pc/src/bootloader_upgrade_tool/gui/styles.py` constants.
- `docs/ui` legacy layout notes are historical reference only and must not
  override the frozen Ribbon layout.

## Operation Flow Rules

All DSP-touching GUI operations must use the Phase 10.8A operation flow:

```text
GUI widget
  -> GUI controller / view model glue
  -> ProgramController or operation-layer wrapper
  -> operations/*
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

- CPU1 Load Image / Run must use `ProgramController`.
- Advanced DSP operations must use the existing Phase 10.8A operation-layer
  flow.
- Old CLI, old workflow, and old GUI backend files are reference only and must
  not be used as the runtime path.
- Do not call `cpu1_upgrade` through subprocess.
- Do not directly call pySerial, sockets, Simulator internals, protocol
  primitives, or `BootProtocolClient` convenience calls from widgets.
- Do not reimplement image parsing, Flash erase/program/verify, metadata
  writes, BOOT_ATTEMPT, APP_CONFIRMED, or RUN sequencing inside GUI widgets.

## Hard Rules

- Use PySide6, not PyQt.
- DSP is always slave. PC GUI is always master.
- SCI `'A'` autobaud is connection-layer behavior, not a protocol frame.
- Use Program naming, not Download.
- Old DFU-as-normal-flow guidance is obsolete for Phase 11 GUI.
- `SERVICE_ATTACH` must not be exposed as a public GUI action.
- `verify_flash_image()` does not write `IMAGE_VALID`; `append_image_valid()`
  writes `IMAGE_VALID` separately.
- `run_flash_app()` does not write `BOOT_ATTEMPT`; `append_boot_attempt()`
  writes `BOOT_ATTEMPT` separately.
- Do not copy TI trademarks, logos, icons, screenshots, or proprietary assets.

## Testing Rules

- New GUI tests should cover GUI glue only.
- Do not duplicate existing operation sequencing tests.
- GUI tests must use fake session factories / fake dependencies.
- GUI tests must not open real COM ports, perform real autobaud, call
  subprocess, or execute real Flash, metadata, RUN, reset, W5300, or CPU2
  actions.

## References

For QSS rules, read `references/qss_rules.md`.

`references/gui_refactor_workflow.md` is retired historical reference only. Do
not use it to generate, redesign, or refactor GUI layout.

## Verification

After GUI guidance or GUI glue changes, run:

```powershell
pytest tests/unit/test_gui_static_layout.py
pytest tests/unit/test_gui_flash_sectors.py
pytest tests/unit/gui/test_program_controller.py
```

Run broader unit tests when the change touches firmware parsing, protocol,
operations, session, or transport behavior.
