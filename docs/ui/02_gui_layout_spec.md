# GUI Layout Specification

## Main Window

Future PySide6 layout:

```text
MainWindow
  TopBar
  Body
    SideNav
    QStackedWidget
  BottomConsole
```

Use `QStackedWidget` for pages. The first screen should be the usable operation
workflow, not a landing page.

## Pages

| Page | Purpose |
|---|---|
| Device | Connection status, transport, serial parameters, device summary |
| Firmware | `.out` selection, firmware conversion, firmware summary |
| Operation | Erase, Program, Verify, DFU, Run, progress |
| Memory | Memory map and sector information; no RAM_LOAD exposure in MVP |
| Logs | Full log view, filters, save controls |
| Settings | hex2000 path, defaults, timeouts, debug trace switches |

## Operation Page Cards

### Firmware Image Card

Contains:

- `Firmware Image (.out)`;
- Browse;
- image status;
- firmware summary.

### Target Device Card

Contains:

- Transport;
- Serial Port;
- Baud Rate;
- Connect;
- Get Device Info;
- Target Device Summary.

GUI code must still use the PC IO Device abstraction. It must not call pySerial,
socket, or Simulator directly outside the IO layer.

### Flash Operation Card

Contains:

- Erase sector mask;
- Erase;
- Program;
- Verify;
- DFU;
- Run;
- progress.

`DFU` is a GUI workflow: `Erase + Program + Verify`. It is not a DSP protocol
command.

## Reset Placement

`Reset` is listed in MVP scope, but `docs/04_pc_gui_requirements.md` says RESET
must not be exposed until deterministic reset policy is implemented and
advertised by DeviceInfo flags.

Future UI must not place Reset in the main operation card. If kept for
developer testing, put it under Settings / Advanced / Experimental and keep it
hidden or disabled by policy.
