# Phase 11 Batch 6 Settings Page Validation

## Scope

Batch 6 replaces the Settings placeholder with one static `SettingsPage`.

Implemented layout:

```text
SettingsPage
├─ Current Configuration
│  ├─ Connection
│  ├─ Target
│  └─ Program Options
└─ Global Configuration
   ├─ Tools
   ├─ Flash Service
   ├─ Transport
   ├─ Logging
   └─ GUI Behavior
```

Each scope contains a category list, category content stack, and fixed action
bar. Current and Global action buttons are visible but disabled because settings
persistence is outside this batch.

## Frozen boundaries

This batch does not:

- read or write settings JSON;
- scan or open COM ports;
- connect to a DSP or perform autobaud;
- call `operations/*`, `images/*`, `session/*`, `transport/*`, or `protocol/*`;
- open file/folder dialogs;
- attach `flash_lib` or expose `SERVICE_ATTACH`;
- erase/program/verify Flash or write metadata;
- implement CPU2 or W5300 runtime behavior;
- modify DSP, `flash_lib`, linker, protocol, or Flash layout.

CPU2 Flash Service fields and TCP/W5300 content remain visible but disabled.
Descriptor addresses are read-only and explicitly resolved from map/symbol data;
they are not manually entered or hardcoded.

## Software validation

```powershell
$env:QT_QPA_PLATFORM = "offscreen"

python -m pytest `
  .\tests\unit\test_gui_settings_page.py `
  .\tests\unit\test_gui_static_layout.py `
  .\tests\unit\test_gui_navigation.py `
  .\tests\unit\test_gui_ribbon.py `
  .\tests\unit\test_gui_common_widgets.py `
  .\tests\unit\test_gui_theme_contract.py `
  .\tests\unit\test_gui_view_import_boundaries.py `
  -q

python -m pytest `
  .\tests\unit\test_gui_flash_sectors.py `
  .\tests\unit\test_phase_10_8a_operations.py `
  -q

git diff --check
```

## Manual static review

```powershell
python -m bootloader_upgrade_tool
```

Review:

- Settings is no longer a placeholder;
- Current and Global scope tabs switch locally;
- category rows switch the content stack;
- action bars remain fixed at the bottom;
- CPU2 Flash Service and TCP/W5300 are visible and disabled;
- no Erase Settings or Entire Flash option appears;
- no `SERVICE_ATTACH` primary action appears;
- 1280x760, 1440x900, and 1920x1080 have no outer horizontal scrolling;
- no real hardware activity occurs.
