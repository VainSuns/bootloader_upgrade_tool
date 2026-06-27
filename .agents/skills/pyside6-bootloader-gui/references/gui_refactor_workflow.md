# GUI Refactor Workflow

Do the refactor in small phases. The shortest safe path is to keep behavior in place while replacing the shell around it.

## UI-0: Docs and Skill

Add `docs/ui/*`, GUI `AGENTS.md`, and this Skill. Do not modify Python business code.

## UI-1: Static Shell

Create the new main-window structure:

```text
TopBar
SideNav
QStackedWidget
BottomConsole
```

Keep existing workflows callable. Preserve test-facing `MainWindow` attributes through direct ownership or property forwarding.

## UI-2: Components

Split UI construction into pages and widgets:

```text
pages/operation_page.py
pages/device_page.py
pages/firmware_page.py
pages/logs_page.py
pages/settings_page.py
widgets/top_bar.py
widgets/side_nav.py
widgets/card.py
widgets/log_console.py
```

Do not change protocol, IO Device, or workflow behavior in this phase.

## UI-3: Theme

Add `theme.qss` and a tiny loader. Python sets object names and dynamic properties; QSS owns visuals.

## UI-4: Reconnect Behavior

Wire the new widgets to existing firmware conversion, `ProtocolClient`, `UpgradeWorkflow`, and IO Device APIs.

## UI-5: Operation Worker

Move these operations off the GUI thread:

```text
Erase
Program
Verify
DFU
Run
```

Use signals for progress, log, finished, failed, and cancelled. Remove progress handling that depends on `QApplication.processEvents()`.

## UI-6: Acceptance

Add console save and screenshot acceptance only when the environment can produce repeatable offscreen screenshots.

## Compatibility Surface

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
