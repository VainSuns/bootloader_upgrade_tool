# Phase 11 Batch 4 Validation

## Scope

Batch 4 migrates the executable GUI shell to the approved V1.0 hierarchy:

- modular four-tab Ribbon;
- vertical workspace Splitter;
- horizontal navigation/page Splitter;
- seven registered static placeholder pages;
- one global Console pane;
- formal Fusion/font/palette/tokenized-QSS application startup.

It does not connect to serial/TCP, scan COM ports, perform autobaud, call
`operations/*`, touch real Flash or metadata, transfer execution, reset a DSP,
or implement CPU2/W5300 backends.

## Required environment

- Python 3.12.x
- PySide6 6.8 or newer, below 7
- pytest
- `QT_QPA_PLATFORM=offscreen` for headless tests

## Commands

```powershell
python -m py_compile `
  .\pc\src\bootloader_upgrade_tool\gui\app.py `
  .\pc\src\bootloader_upgrade_tool\gui\main_window.py `
  .\pc\src\bootloader_upgrade_tool\gui\console_splitter.py `
  .\pc\src\bootloader_upgrade_tool\gui\styles.py `
  .\pc\src\bootloader_upgrade_tool\gui\pages\__init__.py `
  .\pc\src\bootloader_upgrade_tool\gui\pages\placeholder_page.py

$env:QT_QPA_PLATFORM = "offscreen"

python -m pytest `
  .\tests\unit\test_gui_static_layout.py `
  .\tests\unit\test_gui_app_theme_entry.py `
  .\tests\unit\test_gui_console_shell.py `
  .\tests\unit\test_gui_navigation.py `
  .\tests\unit\test_gui_ribbon.py `
  .\tests\unit\test_gui_common_widgets.py `
  .\tests\unit\test_gui_console_widget.py `
  .\tests\unit\test_gui_theme_contract.py `
  .\tests\unit\test_gui_icon_manifest.py `
  .\tests\unit\test_gui_console_highlighter.py `
  .\tests\unit\test_gui_view_import_boundaries.py `
  -q

python -m pytest `
  .\tests\unit\test_gui_flash_sectors.py `
  .\tests\unit\test_phase_10_8a_operations.py `
  -q

git diff --check
```

## Manual static smoke test

```powershell
python -m bootloader_upgrade_tool.gui.app
```

Verify only local GUI behavior:

- default size is 1440 x 900 and hard minimum is 1180 x 680;
- Operate is the selected Ribbon tab;
- CPU1 Program is the selected page;
- all seven pages clearly display `Layout Placeholder`;
- Logs and Settings Ribbon actions navigate locally;
- Console is one global pane, collapses to 34 px, and restores its prior height;
- a 1180 x 680 launch starts with Console collapsed;
- no COM scan, connection attempt, hardware success claim, or DSP action occurs.

## Expected boundary result

`app.py`, `main_window.py`, `styles.py`, `pages/placeholder_page.py`, and all
Batch 1-3 View modules must not import operations, images, session, transport,
protocol, targets, pyserial, subprocess CLI workflows, or program_controller.
