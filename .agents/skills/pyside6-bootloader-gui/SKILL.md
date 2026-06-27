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
- `docs/ui/*.md`
- `docs/04_pc_gui_requirements.md`
- `tests/unit/test_gui.py`

## Hard Rules

- Use PySide6, not PyQt.
- Keep GUI, protocol, firmware parsing, workflow, and IO Device concerns separate.
- GUI must call core / workflow / IO Device layers; it must not directly call pySerial, sockets, Simulator internals, or Flash logic.
- DSP is always slave. PC GUI is always master.
- SCI `'A'` autobaud is connection-layer behavior, not a protocol frame.
- DFU is GUI flow: `Erase + Program + Verify`.
- Use Program naming, not Download.
- Do not expose Reset as a main operation until deterministic reset policy exists and DeviceInfo advertises support.
- Do not copy TI trademarks, logos, icons, screenshots, or proprietary assets.

## Workflow

1. Update or read UI docs first.
2. Change static UI structure before connecting business logic.
3. Reuse existing firmware, workflow, protocol, and IO Device APIs.
4. Preserve current `MainWindow` test-facing attributes or update tests in the same change with the reason documented.
5. Add QSS through `theme.qss`; avoid large inline `setStyleSheet()` blocks.
6. Move long-running operations to workers only after the static layout is stable.

For the staged plan, read `references/gui_refactor_workflow.md`.
For QSS rules, read `references/qss_rules.md`.

## Verification

After GUI code changes, run:

```powershell
pytest tests/unit/test_gui.py
```

Run broader unit tests when the change touches firmware parsing, protocol, workflow, or IO Device behavior.
