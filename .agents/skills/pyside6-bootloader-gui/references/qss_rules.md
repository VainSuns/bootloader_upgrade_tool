# QSS Rules

Centralize future GUI styling in:

```text
pc/src/bootloader_upgrade_tool/gui/resources/styles/theme.qss
```

## Allowed in Python

- `setObjectName(...)`
- dynamic Qt properties such as `role`, `state`, and `level`
- enabled / disabled state
- text and signal wiring

## Avoid in Python

- large `setStyleSheet()` blocks
- color constants scattered through widgets
- style decisions mixed with protocol, IO, firmware parsing, or workflow logic

## Suggested Properties

```text
role = primary | secondary | danger
state = disconnected | connected | busy | complete | warning | error
level = info | warn | error | success | proto
```

## Suggested Object Names

```text
TopBar
SideNav
MainStack
BottomConsole
FirmwareCard
TargetDeviceCard
OperationCard
StatusBadge
```

## Theme Direction

Use a restrained engineering-tool palette:

```text
main background: #F5F7FA
card background: #FFFFFF
card border: #D9DEE7
top bar: #17324D
sidebar: #263238
primary: #1976D2
success: #2E7D32
warning: #F9A825
error: #C62828
console background: #FFFFFF
console panel: #EEF2F6
console text: #0F172A
```

No TI trademarks, logos, copied icons, or proprietary visual assets.
