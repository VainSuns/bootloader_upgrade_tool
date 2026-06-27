# GUI Design Goal

## Current State

The current PySide6 GUI is an MVP form window. It exposes the required bootloader
fields and flows, but most controls live in one `QFormLayout` and one
`application.py` file.

This is acceptable for Phase 3 validation. It is not the target product UI.

## Target

The next GUI should become a professional DSP bootloader programming tool:

- keep Python 3.12 and PySide6;
- keep the PC GUI as protocol master and the DSP as slave;
- keep all transport access behind the IO Device abstraction;
- keep Program naming, not Download;
- present DFU as `Erase + Program + Verify`;
- keep Flash/RAM alignment rules visible in validation and help text where
  needed.

## Reference Boundary

The UI may borrow information architecture ideas from tools such as TI
UniFlash: top application bar, navigation, task pages, status, and console.

It must not copy TI trademarks, logos, icons, layouts, screenshots, or
proprietary assets.

## Product Direction

Future main window structure:

```text
 Top Application Bar
 + Left Navigation Sidebar
 + Main Card-Based Content Area
 + Bottom Console Panel
```

Do not continue expanding a single large form window.
