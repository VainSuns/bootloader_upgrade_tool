# GUI Component Specification

## TopBar

Shows:

- product name: `DSP28377D Bootloader Upgrade Tool`;
- connection state badge;
- Settings action.

It must not contain firmware, transport, or Flash operation forms.

## SideNav

Navigation items:

- Device;
- Firmware;
- Operation;
- Memory;
- Logs;
- Settings.

Use `QStackedWidget` page switching. Keep labels stable for tests and screenshots.

## StatusBadge

Small reusable state indicator. It should map dynamic Qt properties to QSS
states instead of inline styles.

Suggested property:

```text
state = disconnected | connected | busy | complete | warning | error
```

## Card

Simple titled container for one task group. Do not put cards inside cards.

## FirmwareCard

Owns firmware UI only:

- `.out` path display;
- Browse;
- conversion status;
- firmware summary.

It may call existing firmware conversion helpers through the main window or a
controller. It must not contain transport or Flash operation controls.

## TargetDeviceCard

Owns target connection UI:

- Transport;
- Serial Port;
- Baud Rate;
- Connect / Cancel;
- Get Device Info;
- Target Device Summary.

It must use the IO Device abstraction through existing core/workflow plumbing.

## OperationCard

Owns bootloader actions:

- Erase sector mask;
- Erase;
- Program;
- Verify;
- DFU;
- Run;
- progress.

Reset must not be a main operation button.

## TargetControlCard

Optional future card for policy-gated actions. Use for hidden or disabled
advanced controls such as Reset after deterministic policy exists.

## LogConsole

Owns console presentation:

- append timestamped entries;
- use a light background consistent with the main window;
- display levels: `INFO`, `WARN`, `ERROR`, `SUCCESS`, `PROTO`;
- Clear;
- Save `.log`;
- Save `.jsonl`;
- raw protocol trace visibility controlled by Settings.
- collapsed console uses a compact bar; message count uses a small red
  notification badge, not a large filled block.

## SettingsPage

Owns advanced configuration:

- `hex2000.exe` path;
- default baud rate;
- timeout;
- retry count;
- packet size;
- default erase sector mask;
- log level;
- raw protocol trace switch.

Settings must not implement protocol, serial, socket, or Flash behavior.

## Control Room Blue Component Rules

Use these rules for current and future PySide6 widgets. Keep visuals in QSS;
Python should only set object names, dynamic properties, enabled state, and
text.

### Buttons

- Primary buttons are for `Program`, `DFU`, `Connect`, and the single strongest
  action in a page.
- Secondary buttons are for `Browse`, `Get Device Info`, `Clear`, `Save`, and
  diagnostic actions.
- Danger buttons are only for destructive or policy-gated actions. `Reset`
  stays disabled/advanced until DeviceInfo and policy allow it.
- Tool buttons in top bars, console headers, and compact command rows should
  use smaller height but the same focus and disabled rules.

### Inputs And Selectors

- `QLineEdit`, `QComboBox`, `QSpinBox`, and related field controls use white
  backgrounds by default, blue borders on focus, and subtle gray backgrounds
  for read-only values.
- Placeholder text must be muted; do not rely on placeholder text as the only
  label.
- Read-only is not disabled. Read-only fields remain legible and selectable.

### Selection Controls

- `QCheckBox` and `QRadioButton` use blue checked states and visible focus.
- Do not use color alone for safety-critical state; pair status text with the
  selected/checked control.

### Tables And Trees

- `QTableView`, `QTreeView`, and list-like controls use white surfaces, subtle
  row separators, light blue selected rows, and compact row heights.
- Numeric, address, and protocol columns should use monospaced text when a
  dedicated delegate or widget is introduced.

### Tabs, Menus, Dialogs, And Tooltips

- `QTabWidget` tabs use the same selected blue accent as SideNav.
- `QMenu` and popups use white surfaces, small radius, and subtle shadow/border.
- `QDialog` uses a white body with a light header/footer separation if needed.
- `QToolTip` uses a dark neutral surface with light text.

### Status And Feedback

- Status badges use semantic states: `disconnected`, `connected`, `busy`,
  `complete`, `warning`, `error`.
- Progress bars use stable dimensions and must not shift layout as values
  change.
- Error, warning, and success states must remain readable on both cards and
  the top bar.
