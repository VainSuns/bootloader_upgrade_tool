# AGENTS.md

## GUI Rules

This directory contains the PySide6 GUI for the DSP28377D Bootloader Upgrade
Tool.

## Required Reading

Before editing GUI code, read:

- repository `AGENTS.md`;
- `docs/phase11_gui_visual_layout_contract.md`;
- `docs/phase11_gui_mvp_requirements.md`;
- `docs/phase_10_8a_operation_library_usage_example.md`;
- `docs/04_pc_gui_requirements.md`;
- `docs/ui/*.md`;
- `pc/src/bootloader_upgrade_tool/gui/global_settings.py`;
- `pc/src/bootloader_upgrade_tool/gui/program_controller.py`;
- `tests/unit/test_gui.py`;
- this file.

## Phase 11 Runtime Path

GUI code must follow the Phase 11 operation-library path:

```text
GUI widgets
  -> GUI controller
  -> operations/*
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

Do not implement the GUI as:

```text
GUI button -> subprocess -> cpu1_upgrade CLI
GUI widget -> direct protocol command construction
GUI widget -> direct BootProtocolClient convenience calls
GUI widget -> direct serial/socket/Simulator access
GUI widget -> duplicated Flash or metadata state machine
GUI widget -> old workflow / IO Device layer
```

## Hard Constraints

- Use PySide6, not PyQt.
- DSP is always slave; PC GUI is always master.
- SCI `'A'` autobaud is connection-layer behavior, not a protocol frame.
- Use Program naming, not Download.
- Old DFU-as-normal-flow guidance is obsolete for Phase 11 GUI.
- `verify_flash_image()` only verifies data; it does not write `IMAGE_VALID`.
- `append_image_valid()` writes `IMAGE_VALID` separately.
- `run_flash_app()` only sends RUN; it does not write `BOOT_ATTEMPT`.
- `append_boot_attempt()` writes `BOOT_ATTEMPT` separately.
- `SERVICE_ATTACH` is internal operation-library behavior and must not be
  exposed as a public GUI action.
- Do not expose Reset as a main operation until deterministic policy exists and
  DeviceInfo advertises support.
- Do not copy TI trademarks, logos, icons, screenshots, or proprietary assets.

## Phase 11 UI Rules

- `MainWindow` central widget top-level order is exactly: `headerFrame`,
  `connectionStrip`, `bodyFrame`, `bottomConsole`.
- `connectionStrip` is a direct top-level child below `headerFrame` and above
  `bodyFrame`.
- `connectionStrip` is not inside CPU1 page, `pageStack`, a scroll area, a card,
  or a `QGroupBox`.
- `connectionStrip` contains Port, Baud, one stateful connection button, and
  Status.
- `connectionStrip` has no separate Disconnect button and no timeout fields.
- Navigation is exactly:
  `Program` / `CPU1`, `Tools` / `Advanced`, `Logs`, `Settings`.
- CPU1 page title is `CPU1 Program`.
- CPU1 page sections are: App Image, Options, Operations, Status Summary.
- `Load Image` and `Run` are the only normal operation buttons.
- `Confirm App`, `Auto Run after Load`, and `Force Load` are checkboxes under
  Options, not buttons.
- Do not expose autobaud always/skip options in `connectionStrip`.
- Do not place TX timeout, RX timeout, autobaud timeout, Flash service paths,
  `hex2000`, or temporary-directory fields in `connectionStrip`; those belong
  in Global Settings.
- Keep normal workflow actions separate from Advanced/debug operations.
- Do not keep or recreate Operation or Firmware as normal workflow pages.
- Do not expose Erase, Program, Verify, DFU, or SERVICE_ATTACH as normal GUI
  buttons.
- Simulator is not a Phase 11 GUI dependency.
- Do not expand the old form-style `MainWindow` UI.

## Styling

- Centralize visual styling in QSS:
  `pc/src/bootloader_upgrade_tool/gui/resources/styles/theme.qss`.
- Python may set object names, dynamic properties, enabled state, and text.
- Do not commit large inline `setStyleSheet()` blocks.

## Compatibility

Legacy `MainWindow` attributes and methods are temporary compatibility only.
Preserve them for existing tests or update tests in the same change, but do not
use them as a reason to expand the old form-style UI.

Temporary compatibility surface:

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

## Test Boundaries

GUI tests must not:

- open a real COM port;
- run real SCI autobaud;
- call subprocess or the old `cpu1_upgrade` CLI;
- erase/program/verify real Flash;
- write real metadata;
- send real RUN or reset actions;
- perform W5300/TCP or CPU2 bring-up.

Use injected fakes for session/connection factories and hardware-touching
steps.

## Verification

After relevant GUI changes, run:

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_gui.py
.venv\Scripts\python.exe -m pytest tests/unit/gui/test_global_settings.py
.venv\Scripts\python.exe -m pytest tests/unit/gui/test_program_controller.py
.venv\Scripts\python.exe -m pytest tests/unit/gui/test_connection_ribbon.py
```

Run the connection-ribbon test only if it exists. Run broader unit tests when
the change touches firmware parsing, protocol, operations, session, transport,
or workflow behavior.
