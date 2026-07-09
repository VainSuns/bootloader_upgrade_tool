# Phase 11 GUI Static Layout Skeleton v6

## Scope

This package contains a PySide6 static GUI layout skeleton for Phase 11.

It freezes:

```text
MainWindow layout
Ribbon tabs and groups
Navigation tree
Program CPU1 / CPU2 pages
Session Settings page
Global Settings page
Advanced page and internal tabs
Memory CPU1 / CPU2 pages
Logs page
bottomDock Console
key objectName values
layout size constants
```

It intentionally does **not** implement:

```text
serial transport
autobaud
real COM connection
Flash erase/program/verify
metadata write
RAM load/run
memory read
operation-library wiring
hardware validation
```

The static layout skeleton now has offscreen PySide6 layout smoke tests in
`tests/unit/test_gui_static_layout.py`.  These tests instantiate the window and
check the frozen ribbon, navigation, page, RAM Image, Memory table, Console, and
stable summary `objectName` structure without opening serial ports or invoking
hardware paths.

The old behavior-oriented GUI tests from the pre-Phase-11 `MainWindow` surface
are no longer applicable to this layout-only skeleton.  Flash-sector and App
window boundary checks remain as pure logic tests in
`tests/unit/test_gui_flash_sectors.py`.

Later Codex tasks may wire controller logic to this skeleton, but must not
change the frozen layout or stable `objectName` values unless the user
explicitly approves that contract change.

## v6 layout updates

```text
1. Operate ribbon Status group alignment is fixed.
   CPU1 and CPU2 status indicator rows are now centered inside the Status group.

2. Advanced / RAM Image tab is changed from one Target selector to a left/right layout.
   The Target combo box is removed.

3. RAM Image now contains two parallel cards:
   CPU1 RAM Image
   CPU2 RAM Image

4. CPU1 RAM Image and CPU2 RAM Image keep the same fields:
   Image path
   File name
   Entry point
   Load address
   Image size
   CRC32
   Parse status

5. v5 layout decisions remain preserved:
   Advanced does not use a vertical splitter.
   The bottom dock is named Console only.
   The bottom Console output area keeps left/right margins and a bordered card-like frame.
   Settings sections remain collapsible expanders.
   Memory tables fill the right-side page area with centered text.
```

## Files

```text
pc/src/bootloader_upgrade_tool/gui/
├─ __init__.py
├─ app.py
├─ main_window.py
├─ styles.py
└─ widgets/
   └─ __init__.py
```

## Size constraints encoded in `styles.py`

```text
MainWindow default size: 1440 x 900
MainWindow minimum size: 1280 x 760
Ribbon title row height: 38 px
Ribbon content row height: 112 px
Navigation preferred width: 240 px
Navigation min/max width: 220 / 280 px
bottomDock expanded height: 160 px
bottomDock collapsed height: 30 px
Logs detail default height: 200 px
Memory control bar height: 48 px
Memory default rows: 100
Memory word columns: 16
Advanced tab minimum content width: 900 px
Advanced RAM tab minimum content width: 900 px
Advanced two-column card minimum width: 420 px
Advanced tabs minimum height: 260 px
Advanced result minimum height: 140 px
Program page minimum content width: 860 px
Program App Image minimum height: 150 px
Program Status Summary minimum height: 150 px
Program Details / Result minimum height: 220 px
Settings page minimum content width: 860 px
```

## Layout outline

```text
MainWindow
┌────────────────────────────────────────────────────────────────────┐
│ Bootloader | Session | Operate | View | Settings                   │
├────────────────────────────────────────────────────────────────────┤
│ Ribbon Content                                                     │
├──────────────┬─────────────────────────────────────────────────────┤
│ Navigation   │ Page Content                                        │
│              │                                                     │
├──────────────┴─────────────────────────────────────────────────────┤
│ Console                                                            │
└────────────────────────────────────────────────────────────────────┘
```

## Navigation

```text
Program
  CPU1
  CPU2

Settings

Memory
  CPU1
  CPU2

Advanced

Logs
```

## Settings page layout

```text
Session Settings
└─ ▾ Erase Settings
   ├─ Necessary Sectors Only
   └─ Entire Flash
```

```text
Global Settings
├─ ▾ Tool Paths
├─ ▾ Flash Service
├─ ▾ Default Transport
├─ ▾ Logging
└─ ▾ GUI Behavior
```

## Advanced page layout

```text
Advanced
├─ Advanced tabs
│  ├─ Diagnostics
│  ├─ Flash
│  ├─ Metadata
│  ├─ Execution
│  └─ RAM Image
└─ Result / Details
```

RAM Image tab layout:

```text
RAM Image
├─ Operations
│  ├─ Load
│  └─ Run
└─ RAM Image area
   ├─ CPU1 RAM Image
   │  ├─ Image path
   │  ├─ File name
   │  ├─ Entry point
   │  ├─ Load address
   │  ├─ Image size
   │  ├─ CRC32
   │  └─ Parse status
   └─ CPU2 RAM Image
      ├─ Image path
      ├─ File name
      ├─ Entry point
      ├─ Load address
      ├─ Image size
      ├─ CRC32
      └─ Parse status
```

The RAM Image tab does not show a Target selector. CPU1 and CPU2 have independent image path fields.

No page-level warning banner is shown above the Advanced tabs.

Each Advanced tab owns its own context warning when needed:

```text
Flash:     Advanced Flash operations may modify Flash and metadata.
Metadata:  Advanced metadata operations affect boot decision records.
Execution: Execution operations may transfer control to the target App.
```

## Run for visual review

From a project checkout with PySide6 installed:

```bash
PYTHONPATH=pc/src python -m bootloader_upgrade_tool.gui.app
```

## Rule for later Codex tasks

Later Codex tasks may wire logic to these widgets, but should not redesign the layout.

Do not change:

```text
main window structure
Ribbon tab/group structure
navigation structure
page order
size constants
objectName values
```

without explicit user approval.
