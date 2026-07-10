# Phase 11 Batch 5 Validation

## Scope

Batch 5 replaces the CPU1 and CPU2 Program placeholders with one shared static
`ProgramTargetPage(target="cpu1" | "cpu2")` implementation.

The page includes:

- App Image fields and local Browse/Prepare intent signals;
- Force Load, Auto Run after Load, and Confirm App options;
- no embedded operation-progress panel; future workflow progress uses a dedicated dialog;
- the eight frozen bootability status rows;
- a read-only Details / Result pane with local Copy and Clear controls;
- the frozen 58:42 horizontal workflow/state splitter.

CPU1 controls are local-only and do not access files or hardware. CPU2 remains
visible for layout review, but its workflow controls are disabled in Phase 11.1.

## Prohibited behavior

This batch does not:

- open or parse an image file;
- import or call `images/*` or `operations/*`;
- create a session or access protocol/transport layers;
- scan/open COM ports or perform autobaud;
- erase/program/verify Flash or write metadata;
- send RUN or Reset;
- expose Erase, Program Only, Verify Only, or SERVICE_ATTACH on Program pages;
- implement CPU2 or W5300 backend behavior;
- modify DSP code, downloaded flash_lib, linker files, Flash layout, metadata
  layout, TargetProfile, or CommandSet.

## Required environment

- Python 3.12.x
- PySide6 6.8 or newer, below 7
- pytest
- `QT_QPA_PLATFORM=offscreen` for headless tests

## Static compilation

```powershell
python -m py_compile `
  .\pc\src\bootloader_upgrade_tool\gui\pages\program_page.py `
  .\pc\src\bootloader_upgrade_tool\gui\pages\__init__.py `
  .\pc\src\bootloader_upgrade_tool\gui\main_window.py `
  .\pc\src\bootloader_upgrade_tool\gui\layout_metrics.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\ribbon\operate_ribbon.py `
  .\tests\unit\test_gui_program_pages.py `
  .\tests\unit\test_gui_static_layout.py `
  .\tests\unit\test_gui_view_import_boundaries.py
```

## GUI tests

```powershell
$env:QT_QPA_PLATFORM = "offscreen"

python -m pytest `
  .\tests\unit\test_gui_program_pages.py `
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
```

## Backend regression tests

```powershell
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

- CPU1 Program is the default page and no longer shows `Layout Placeholder`;
- CPU2 Program uses the same visual structure and its workflow controls are
  disabled;
- both Program pages show the App Image, Options, Status Summary, and Details /
  Result cards without an embedded Operation Progress card;
- the eight frozen status rows are visible;
- Program pages do not show Erase, Program Only, Verify Only, SERVICE_ATTACH,
  Load Image, or Run buttons;
- future workflow progress is reserved for a dedicated dialog rather than the page;
- the compact SCI/TCP transport group and collapsed Console header controls are not clipped;
- Details Copy/Clear and CPU1 option toggles are local-only;
- no file dialog, COM scan, connection attempt, hardware success claim, or DSP
  action occurs.
