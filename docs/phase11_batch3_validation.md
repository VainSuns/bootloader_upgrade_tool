# Phase 11 Batch 3 Validation

Batch 3 adds the frozen `PageId` contract, local-only navigation synchronization,
and the modular Session, Operate, View, and Settings Ribbon pages.

## Scope

Batch 3 does not modify `app.py`, `main_window.py`, page implementations,
operations, images, sessions, transports, protocols, targets, DSP code, Flash
behavior, metadata behavior, CPU2 backend behavior, or W5300 behavior.

The Operate Ribbon does not scan COM ports or open a transport. Session and
Global Settings persistence buttons remain disabled. TCP remains visible and
disabled.

## Required environment

- Python 3.12.x
- PySide6 6.8 or newer, below 7
- pytest 8 or newer, below 10
- `QT_QPA_PLATFORM=offscreen` for headless GUI tests

## Commands

```powershell
python -m py_compile `
  .\pc\src\bootloader_upgrade_tool\gui\navigation.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\navigation_panel.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\ribbon\ribbon_shell.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\ribbon\session_ribbon.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\ribbon\operate_ribbon.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\ribbon\view_ribbon.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\ribbon\settings_ribbon.py

$env:QT_QPA_PLATFORM = "offscreen"

python -m pytest `
  .\tests\unit\test_gui_navigation.py `
  .\tests\unit\test_gui_ribbon.py `
  .\tests\unit\test_gui_view_import_boundaries.py `
  .\tests\unit\test_gui_common_widgets.py `
  .\tests\unit\test_gui_console_widget.py `
  .\tests\unit\test_gui_theme_contract.py `
  .\tests\unit\test_gui_icon_manifest.py `
  .\tests\unit\test_gui_console_highlighter.py `
  -q

python -m pytest `
  .\tests\unit\test_gui_static_layout.py `
  .\tests\unit\test_gui_flash_sectors.py `
  .\tests\unit\test_phase_10_8a_operations.py `
  -q

git diff --check
```

## Expected results

- `PageId` contains exactly seven approved values.
- Navigation order is Program/CPU1/CPU2, Settings, Memory/CPU1/CPU2,
  Advanced, Logs.
- `NavigationRouter.navigate_to()` synchronizes the tree and page stack.
- Ribbon order is Session, Operate, View, Settings; Operate is selected.
- Session persistence controls are visible and disabled.
- SCI is visible without COM scanning; TCP is visible and disabled.
- CPU1 and CPU2 status rows remain visible.
- View and Settings pages emit local intents only.
- No View module imports backend runtime layers.

No command in this checklist connects to real hardware.
