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

## Theme Contract

The approved theme is `Control Room Blue`. Keep the canonical implementation in
`pc/src/bootloader_upgrade_tool/gui/resources/styles/theme.qss`.

The QSS must cover common Qt controls even when the current window does not use
all of them yet:

```text
QPushButton
QToolButton
QLineEdit
QTextEdit
QPlainTextEdit
QComboBox
QSpinBox
QDoubleSpinBox
QCheckBox
QRadioButton
QProgressBar
QTabWidget
QTableView
QTreeView
QListView
QMenu
QDialog
QMessageBox
QToolTip
QScrollBar
QSplitter
```

All controls should define default, hover, focus, disabled, and selected or
checked states where the widget supports them. Future widgets should reuse
existing semantic properties before adding new object names.

## Property Contract

Use these dynamic properties consistently:

```text
variant = primary | secondary | ghost | toolbar | consoleTool | danger | dangerGhost
role = card | cardTitle | summary | fieldLabel | sectionTitle | expanderContentLabel
state = disconnected | connected | busy | complete | warning | error | success
level = info | warn | error | success | proto
```

Add a new property value only when an existing one cannot express the visual
role. Document any new value in this file before relying on it in QSS.
