# Phase 11 Batch 2 Validation

Batch 2 adds reusable GUI-only widgets. It does not modify `app.py`,
`main_window.py`, page layouts, operation sequencing, protocol, transport, DSP,
Flash, metadata, CPU2 backend, or W5300.

## Files

```text
pc/src/bootloader_upgrade_tool/gui/widgets/
  __init__.py
  card.py
  page_header.py
  status_widgets.py
  form_rows.py
  navigation_panel.py
  console_widget.py

tests/unit/
  test_gui_common_widgets.py
  test_gui_console_widget.py
  test_gui_view_import_boundaries.py
```

## Verification

Run from the repository root with Python 3.12 and the development dependencies:

```powershell
python -m py_compile `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\__init__.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\card.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\page_header.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\status_widgets.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\form_rows.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\navigation_panel.py `
  .\pc\src\bootloader_upgrade_tool\gui\widgets\console_widget.py

$env:QT_QPA_PLATFORM = "offscreen"

python -m pytest `
  .\tests\unit\test_gui_common_widgets.py `
  .\tests\unit\test_gui_console_widget.py `
  .\tests\unit\test_gui_view_import_boundaries.py `
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

## Manual GUI-only review

Instantiate the common widgets in an offscreen or local preview harness and check:

- cards have no shadow and use the themed border/header;
- status badges always include text;
- status dots remain auxiliary indicators;
- Browse emits `browseRequested` but does not open a file dialog;
- Navigation emits stable page objects but does not access a page stack;
- Console is a `QPlainTextEdit`, uses no wrap, limits blocks, copies plain text,
  and emits expansion state without managing splitter sizes.

No validation step may open a COM port or execute Flash, metadata, RUN, reset,
CPU2, or W5300 behavior.
