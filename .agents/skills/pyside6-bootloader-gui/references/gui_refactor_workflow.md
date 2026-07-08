# GUI Refactor Workflow

Do Phase 11 GUI work in small phases. The shortest safe path is to replace legacy GUI structure with the Phase 11 shell while keeping operation-library semantics unchanged.

## UI-0: Docs and Skill

Add `docs/ui/*`, GUI `AGENTS.md`, and this Skill. Do not modify Python business code.

## UI-1: Static Shell

Create the new main-window structure:

```text
headerFrame
connectionStrip
bodyFrame
bottomConsole
```

The top-level central widget order must be exactly:

```text
headerFrame
connectionStrip
bodyFrame
bottomConsole
```

`connectionStrip` is a direct top-level child below `headerFrame` and above `bodyFrame`; it is not inside CPU1 page, `pageStack`, a scroll area, a card, or a `QGroupBox`.

`connectionStrip` contains only Port, Baud, one stateful connection button, and Status. It has no separate Disconnect button and no timeout fields.

Navigation is exactly:

```text
Program
  CPU1
Tools
  Advanced
Logs
Settings
```

Preserve temporary test-facing `MainWindow` attributes through direct ownership or property forwarding, but do not use them to expand the old form-style UI.

## UI-2: Components

Split UI construction into pages and widgets:

```text
pages/cpu1_program_page.py
pages/advanced_page.py
pages/logs_page.py
pages/settings_page.py
widgets/header_frame.py
widgets/connection_strip.py
widgets/navigation.py
widgets/card.py
widgets/log_console.py
```

CPU1 page title is `CPU1 Program`. CPU1 page sections are App Image, Options, Operations, Status Summary.

Do not recreate Operation or Firmware as normal workflow pages.

Do not change protocol, session, transport, operations, or `ProgramController` behavior in this phase.

## UI-3: Theme

Add `theme.qss` and a tiny loader. Python sets object names and dynamic properties; QSS owns visuals.

## UI-4: Reconnect Behavior

Wire the new widgets through:

```text
GUI widgets
  -> GUI controller
  -> operations/*
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

Do not wire GUI widgets to subprocess, `cpu1_upgrade`, direct protocol primitives, direct `BootProtocolClient` convenience calls, direct serial/socket/Simulator access, old workflow / IO Device layers, or duplicated Flash/metadata state machines.

## UI-5: Operation Worker

Move the normal CPU1 operations off the GUI thread:

```text
Load Image
Run
```

Use signals for progress, log, finished, failed, and cancelled. Remove progress handling that depends on `QApplication.processEvents()`.

Normal CPU1 page operation buttons are only `Load Image` and `Run`.

`Confirm App`, `Auto Run after Load`, and `Force Load` are checkboxes under Options, not buttons.

`SERVICE_ATTACH` must not be exposed as a public GUI action.

`verify_flash_image()` does not write `IMAGE_VALID`; `append_image_valid()` writes `IMAGE_VALID` separately.

`run_flash_app()` does not write `BOOT_ATTEMPT`; `append_boot_attempt()` writes `BOOT_ATTEMPT` separately.

Erase, Program, Verify, DFU, and Simulator-dependent GUI workflows are obsolete for Phase 11 normal GUI work.

## UI-6: Acceptance

Add console save and screenshot acceptance only when the environment can produce repeatable offscreen screenshots.

GUI tests must not open real COM ports, perform real autobaud, call subprocess, or execute real Flash, metadata, RUN, reset, W5300, or CPU2 actions. Use fake session factories and fake dependencies.

## Temporary Compatibility Surface

Keep these stable unless tests are updated in the same change:

```text
window.baudrate
window.status_label
window.workflow
window.operation_buttons
window.device_summary
window.firmware_summary
window.log_view
window._connect_device()
window._get_device_info()
```
