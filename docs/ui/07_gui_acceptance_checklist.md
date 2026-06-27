# GUI Acceptance Checklist

Use this checklist for future GUI refactor PRs.

## Layout

- [ ] Main window has a top application bar.
- [ ] Main window has a left sidebar.
- [ ] Main area is card-based and grouped by task.
- [ ] Bottom console is visible during operations.
- [ ] The UI is no longer a single large `QFormLayout` form.
- [ ] Text fits in controls on expected Windows desktop sizes.

## Functionality

- [ ] Existing fields are still available: `.out`, transport, serial port,
  baud rate, erase sector mask, firmware summary, device summary, progress,
  logs.
- [ ] `hex2000.exe` path is available in Settings, not as a primary operation
  field.
- [ ] DFU remains `Erase + Program + Verify`.
- [ ] Program / Verify Flash data still uses 8-word alignment and `0xFFFF`
  padding.
- [ ] RamLoadData is not given Flash alignment rules.
- [ ] Reset is not exposed as a main operation.

## Boundaries

- [ ] GUI uses the IO Device abstraction.
- [ ] GUI does not directly call pySerial, socket, or Simulator outside the IO
  layer.
- [ ] Protocol behavior is unchanged unless explicitly requested.
- [ ] DSP code is unchanged unless explicitly requested.
- [ ] Style is centralized in QSS.
- [ ] Python does not contain large inline styles.

## Compatibility

- [ ] `tests/unit/test_gui.py` passes.
- [ ] Relevant unit tests pass.
- [ ] Current test-facing `MainWindow` attributes are preserved or tests are
  updated in the same change with a documented reason.

## Console

- [ ] Console lines include timestamps.
- [ ] Console supports `INFO`, `WARN`, `ERROR`, `SUCCESS`, and `PROTO`.
- [ ] Raw protocol trace is disabled by default.
- [ ] Logs can be saved as `.log` and `.jsonl` when the feature is implemented.
