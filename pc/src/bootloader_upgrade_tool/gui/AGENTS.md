# AGENTS.md

## GUI Rules

This directory contains the PySide6 GUI for the DSP28377D Bootloader Upgrade
Tool.

## Required Reading

Before editing GUI code, read:

- repository `AGENTS.md`;
- `docs/04_pc_gui_requirements.md`;
- `docs/ui/*.md`;
- `tests/unit/test_gui.py`;
- this file.

## Hard Constraints

- Use PySide6, not PyQt.
- GUI code must not implement protocol framing, serial/socket transport, or
  Flash operation logic.
- GUI code must call existing core, workflow, firmware, and IO Device layers.
- GUI must not directly depend on pySerial, sockets, or Simulator.
- DSP is always slave; PC GUI is always master.
- SCI `'A'` autobaud is connection-layer behavior, not a protocol frame.
- DFU is GUI flow: `Erase + Program + Verify`.
- Use Program naming, not Download.
- Do not expose Reset as a main operation until deterministic policy exists and
  DeviceInfo advertises support.

## UI Direction

Future UI work must move toward:

```text
TopBar + SideNav + card-based pages + BottomConsole
```

Do not keep expanding a single large form-style `MainWindow`.

## Styling

- Centralize visual styling in QSS.
- Future theme path:
  `pc/src/bootloader_upgrade_tool/gui/resources/styles/theme.qss`.
- Python may set object names, dynamic properties, and state.
- Do not commit large inline `setStyleSheet()` blocks.

## Compatibility

Current GUI tests access `MainWindow` attributes and methods. Preserve those
interfaces or update tests in the same change with the reason documented.

Known compatibility surface:

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

## Verification

After GUI code changes, run:

```powershell
pytest tests/unit/test_gui.py
```

Run broader unit tests when the change touches firmware parsing, protocol,
workflow, or IO Device behavior.
