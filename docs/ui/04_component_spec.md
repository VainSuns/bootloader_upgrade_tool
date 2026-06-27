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
- display levels: `INFO`, `WARN`, `ERROR`, `SUCCESS`, `PROTO`;
- Clear;
- Save `.log`;
- Save `.jsonl`;
- raw protocol trace visibility controlled by Settings.

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
