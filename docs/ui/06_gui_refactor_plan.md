# GUI Refactor Plan

This plan is intentionally staged. Do not rewrite UI, workers, protocol, and
workflow in one pass.

## UI-0: Documentation and Skill

Add GUI development docs, GUI-specific AGENTS rules, and a repository Skill.

No Python business code changes.

## UI-1: Static Main Window Frame

Introduce:

```text
main_window.py
TopBar
SideNav
QStackedWidget pages
BottomConsole
```

Keep existing bootloader behavior wired through `MainWindow`. Preserve current
test-facing attributes or provide property forwarding.

## UI-2: Split Widgets and Pages

Move UI construction into:

```text
pages/
widgets/
```

Keep `application.py` thin. Do not change protocol, workflow, or IO Device
behavior in this phase.

## UI-3: Introduce `theme.qss`

Add:

```text
pc/src/bootloader_upgrade_tool/gui/resources/styles/theme.qss
theme.py
```

Move visual styling into QSS. Python only sets object names and dynamic
properties.

## UI-4: Connect Existing Business Logic

Wire the new components to the existing firmware conversion, `ProtocolClient`,
`UpgradeWorkflow`, and IO Device abstraction.

Compatibility targets:

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

Do not remove these without updating tests in the same change.

## UI-5: OperationWorker

Move long-running operations off the GUI thread:

```text
Erase
Program
Verify
DFU
Run
```

Suggested signals:

```text
progress
log
finished
failed
cancelled
```

Remove dependence on `QApplication.processEvents()` in progress handling.

## UI-6: Console Save and Screenshot Acceptance

Add LogConsole save support:

```text
.log
.jsonl
```

Add screenshot acceptance only when the local/offscreen PySide6 environment is
stable enough to make it repeatable.
