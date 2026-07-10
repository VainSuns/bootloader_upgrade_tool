# Phase 11 Batch 9 — Layout Preview Validation

## Scope

Batch 9 adds an explicit static layout-preview launch mode and configurable initial
window size. It does not add a session, transport, controller, image parser,
operation, Flash service, metadata writer, CPU2 runtime, or W5300 runtime.

## Commands

```powershell
python -m bootloader_upgrade_tool --layout-preview
python -m bootloader_upgrade_tool --layout-preview --window-size 1280x760
python -m bootloader_upgrade_tool --layout-preview --window-size 1440x900
python -m bootloader_upgrade_tool --layout-preview --window-size 1920x1080
```

`--window-size` uses logical pixels and rejects sizes below the frozen
`1180x680` minimum.

## Preview data contract

Preview data is clearly labelled with `[Preview]`, `Layout Preview`, or
`LAYOUT PREVIEW MODE` and is populated only when `--layout-preview` is present.
The preview covers:

- CPU1/CPU2 Program image and status layouts;
- Current Settings values;
- Advanced Flash/RAM path lengths and Shared Result;
- CPU1/CPU2 Memory including unread `????` words;
- structured Logs;
- the global Console.

Preview mode never opens a COM port, sends autobaud `A`, creates a session, reads
an image, attaches a Flash service, reads/writes target memory, writes metadata,
or runs/resets a target.

## Manual validation matrix

Review each resolution at Windows scale 100%, 125%, and 150%:

```text
1280x760
1440x900
1920x1080
```

Check every navigation page, all Advanced tabs, Console collapse/expand, table
horizontal scrolling, and splitter minimum sizes.

## Automated validation

```powershell
$env:QT_QPA_PLATFORM = "offscreen"

python -m pytest `
  .\tests\unit\test_gui_layout_preview.py `
  .\tests\unit\test_gui_layout_preview_boundaries.py `
  .\tests\unit\test_gui_static_layout.py `
  .\tests\unit\test_gui_program_pages.py `
  .\tests\unit\test_gui_settings_page.py `
  .\tests\unit\test_gui_advanced_page.py `
  .\tests\unit\test_gui_memory_pages.py `
  .\tests\unit\test_gui_logs_page.py `
  .\tests\unit\test_gui_view_import_boundaries.py `
  -q
```
