# Phase 11 Batch 10 — Cleanup and Validation

## Scope

Batch 10 finalizes the static GUI architecture. It does not connect a target,
open SCI/TCP, invoke operations, read or write Flash/metadata, reset/run a DSP,
or add CPU2/W5300 runtime behavior.

## Cleanup

The following obsolete files are removed:

- `pc/src/bootloader_upgrade_tool/gui/styles.py`
- `pc/src/bootloader_upgrade_tool/gui/pages/placeholder_page.py`

The final navigation API accepts `PageId` only. String page-key compatibility
and the `BootloaderMainWindow.show_page()` wrapper are removed.

Package entry compatibility remains available through:

- `bootloader_upgrade_tool.gui.main`
- `bootloader_upgrade_tool.gui.run`
- `bootloader_upgrade_tool.gui.MainWindow`
- `bootloader_upgrade_tool.gui.application.run`

## Automated matrix

Logical window sizes:

- 1280 × 760
- 1440 × 900
- 1920 × 1080

Qt scale factors:

- 1.00 (100%)
- 1.25 (125%)
- 1.50 (150%)

Run:

```powershell
.\tools\run_phase11_visual_matrix.ps1
```

## Complete regression

```powershell
$env:QT_QPA_PLATFORM = "offscreen"

python -m pytest `
  .\tests\unit\test_gui_phase11_cleanup.py `
  .\tests\unit\test_gui_phase11_final_validation.py `
  .\tests\unit\test_gui_layout_preview.py `
  .\tests\unit\test_gui_static_layout.py `
  .\tests\unit\test_gui_navigation.py `
  .\tests\unit\test_gui_view_import_boundaries.py `
  .\tests\unit\test_gui_theme_contract.py `
  .\tests\unit\test_gui_icon_manifest.py `
  .\tests\unit\test_gui_console_highlighter.py `
  .\tests\unit\test_gui_program_pages.py `
  .\tests\unit\test_gui_settings_page.py `
  .\tests\unit\test_gui_advanced_page.py `
  .\tests\unit\test_gui_sector_selector.py `
  .\tests\unit\test_gui_memory_pages.py `
  .\tests\unit\test_gui_logs_page.py `
  -q

python -m pytest `
  .\tests\unit\test_gui_flash_sectors.py `
  .\tests\unit\test_phase_10_8a_operations.py `
  -q

git diff --check
```

## Manual visual review

Run each logical size and inspect all seven pages:

```powershell
python -m bootloader_upgrade_tool --layout-preview --window-size 1280x760
python -m bootloader_upgrade_tool --layout-preview --window-size 1440x900
python -m bootloader_upgrade_tool --layout-preview --window-size 1920x1080
```

Check that no target control becomes enabled and no hardware operation is
performed.
