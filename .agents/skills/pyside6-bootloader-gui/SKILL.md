---
name: pyside6-bootloader-gui
description: Repository-specific guidance for PySide6 GUI, QSS, UniFlash-style information architecture, and screenshot/acceptance work in the DSP28377D Bootloader Upgrade Tool.
---

# PySide6 Bootloader GUI

Use this Skill when a task touches this repository's GUI, UI layout, PySide6 widgets, QSS, UniFlash-style structure, console, screenshot acceptance, or GUI tests.

## Read First

Before changing GUI code, read:

- `AGENTS.md`
- `pc/src/bootloader_upgrade_tool/gui/AGENTS.md`
- `docs/phase11_gui_visual_layout_contract.md`
- `docs/phase11_gui_mvp_requirements.md`
- `docs/phase_10_8a_operation_library_usage_example.md`
- `docs/04_pc_gui_requirements.md`
- `pc/src/bootloader_upgrade_tool/gui/global_settings.py`
- `pc/src/bootloader_upgrade_tool/gui/program_controller.py`
- `docs/ui/*.md`
- `tests/unit/test_gui.py`

## Hard Rules

- Use PySide6, not PyQt.
- Phase 11 GUI runtime path is: GUI widgets -> GUI controller -> operations/* -> UpgradeSession.client.transact() -> BootProtocolClient / FrameReader -> ByteTransport.
- Old guidance that GUI must call workflow / IO Device layers directly is obsolete.
- GUI must not directly call pySerial, sockets, Simulator internals, protocol primitives, old workflow/CLI layers, or Flash logic.
- DSP is always slave. PC GUI is always master.
- SCI `'A'` autobaud is connection-layer behavior, not a protocol frame.
- Old DFU-as-normal-flow guidance is obsolete for Phase 11 GUI.
- Use Program naming, not Download.
- Normal operation buttons are only `Load Image` and `Run`.
- `Confirm App`, `Auto Run after Load`, and `Force Load` are checkboxes under Options, not buttons.
- `SERVICE_ATTACH` must not be exposed as a public GUI action.
- `verify_flash_image()` does not write `IMAGE_VALID`; `append_image_valid()` writes `IMAGE_VALID` separately.
- `run_flash_app()` does not write `BOOT_ATTEMPT`; `append_boot_attempt()` writes `BOOT_ATTEMPT` separately.
- Do not expose Reset as a main operation until deterministic reset policy exists and DeviceInfo advertises support.
- Do not copy TI trademarks, logos, icons, screenshots, or proprietary assets.

## Phase 11 Layout Contract

- `MainWindow` central widget top-level order is exactly: `headerFrame`, `connectionStrip`, `bodyFrame`, `bottomConsole`.
- `connectionStrip` is a direct top-level child below `headerFrame` and above `bodyFrame`.
- `connectionStrip` is not inside CPU1 page, `pageStack`, a scroll area, a card, or a `QGroupBox`.
- `connectionStrip` contains Port, Baud, one stateful connection button, and Status.
- `connectionStrip` has no separate Disconnect button and no timeout fields.
- Navigation is exactly: Program / CPU1, Tools / Advanced, Logs, Settings.
- CPU1 page title is `CPU1 Program`.
- CPU1 page sections are: App Image, Options, Operations, Status Summary.
- Operation page, Firmware page, Erase, Program, Verify, DFU, and Simulator-dependent GUI workflows are obsolete for Phase 11 normal GUI work.
- Legacy `MainWindow` attributes are temporary compatibility only; do not use them to expand the old form-style UI.

## Workflow

1. Update or read UI docs first.
2. Change static UI structure before connecting business logic.
3. Reuse `ProgramController`, global settings, and `operations/*`.
4. Preserve temporary `MainWindow` compatibility attributes or update tests in the same change with the reason documented.
5. Add QSS through `theme.qss`; avoid large inline `setStyleSheet()` blocks.
6. Move long-running operations to workers only after the static layout is stable.

For the staged plan, read `references/gui_refactor_workflow.md`.
For QSS rules, read `references/qss_rules.md`.

## Verification

After GUI code changes, run:

```powershell
pytest tests/unit/test_gui.py
```

GUI tests must use fake session factories / fake dependencies. They must not open real COM ports, perform real autobaud, call subprocess, or execute real Flash, metadata, RUN, reset, W5300, or CPU2 actions.

Run broader unit tests when the change touches firmware parsing, protocol, operations, session, or transport behavior.
