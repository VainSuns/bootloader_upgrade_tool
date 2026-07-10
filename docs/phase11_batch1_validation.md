# Phase 11 Batch 1 Validation

This checklist applies to the theme, icon, state-property, and Console syntax
foundation introduced by Batch 1.

## Scope

Batch 1 does not change `app.py`, `main_window.py`, page layouts, operation
wiring, transport, protocol, DSP code, Flash behavior, metadata behavior, CPU2,
or W5300.

## Required environment

- Windows or Linux test host
- Python 3.12.x
- PySide6 6.8 or newer, below 7
- `QT_QPA_PLATFORM=offscreen` for headless GUI tests

## Commands

```powershell
python -m py_compile `
  .\pc\src\bootloader_upgrade_tool\gui\layout_metrics.py `
  .\pc\src\bootloader_upgrade_tool\gui\theme_tokens.py `
  .\pc\src\bootloader_upgrade_tool\gui\theme.py `
  .\pc\src\bootloader_upgrade_tool\gui\ui_state.py `
  .\pc\src\bootloader_upgrade_tool\gui\icon_manager.py `
  .\pc\src\bootloader_upgrade_tool\gui\syntax\console_highlighter.py

$env:QT_QPA_PLATFORM = "offscreen"
pytest `
  .\tests\unit\test_gui_theme_contract.py `
  .\tests\unit\test_gui_icon_manifest.py `
  .\tests\unit\test_gui_console_highlighter.py `
  -q

pytest `
  .\tests\unit\test_gui_static_layout.py `
  .\tests\unit\test_gui_flash_sectors.py `
  .\tests\unit\test_phase_10_8a_operations.py `
  -q

git diff --check
```

## Expected results

- All QSS placeholders resolve through `theme_tokens.py`.
- All 130 semantic names and 65 Tabler SVG resources validate.
- A semantic icon renders to a non-null `QIcon`.
- Dynamic properties reject values outside the frozen contract.
- Console levels DEBUG, INFO, WARN/WARNING, ERROR, SUCCESS, and PROTOCOL are
  recognized.
- WARNING and ERROR receive only weak full-line backgrounds.
- Existing static layout and operation-layer tests remain unchanged and pass.

No command in this checklist opens a real COM port or performs real DSP, Flash,
metadata, RUN, reset, CPU2, or W5300 actions.
