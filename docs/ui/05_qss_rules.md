# QSS Rules

## Location

Future QSS belongs here:

```text
pc/src/bootloader_upgrade_tool/gui/resources/styles/theme.qss
```

Do not spread large `setStyleSheet()` blocks through Python files.

## Python Responsibilities

Python may set:

- `objectName`;
- dynamic Qt properties;
- enabled / disabled state;
- text, values, and signal wiring.

Python should not contain bulk visual styling.

## Naming

Use stable object names:

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

Use dynamic properties for state:

```text
role = primary | secondary | danger
state = disconnected | connected | busy | complete | warning | error
level = info | warn | error | success | proto
```

## Separation Rules

- QSS controls visuals.
- GUI widgets control layout and user interaction.
- Core/workflow controls bootloader behavior.
- IO Device controls transport.
- Protocol modules control frames and status.

Do not mix style logic with protocol, IO, firmware parsing, or Flash workflow
logic.

## Inline Style Exception

Tiny temporary styles are allowed only for diagnostics during development. They
must not be committed as the main theme.
