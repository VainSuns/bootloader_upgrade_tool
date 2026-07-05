# Phase 10.6-A Boot Status / Boot Policy Preview

## Scope

Phase 10.6-A only adds a PC-side boot status query and boot policy preview.
It does not change DSP boot behavior.

The DSP / bootloader still waits for GUI/PC after reset. Future automatic boot
decision is only allowed after the GUI/PC wait window times out.

## Tool

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool.tools.boot_status_probe `
  --transport serial `
  --port COM10 `
  --baud 9600
```

The tool uses `GET_METADATA_SUMMARY` and does not send `RUN`, write
`BOOT_ATTEMPT`, or write `APP_CONFIRMED`.

## Policy preview

Automatic App boot is allowed only for the future policy below:

1. First trial run:
   - `IMAGE_VALID` is valid.
   - no `BOOT_ATTEMPT` exists.
   - downloaded flash_lib is ready.
   - `BOOT_ATTEMPT` write succeeds.
   - then jump App.
2. Confirmed App:
   - `IMAGE_VALID` is valid.
   - `BOOT_ATTEMPT` exists.
   - `APP_CONFIRMED` is valid.
   - then jump App.

Phase 10.6-A previews the decision only. It does not perform either jump path.

## Preview reasons

| Condition | automatic boot allowed | Reason |
|---|---|---|
| Metadata invalid | no | `METADATA_INVALID` |
| No valid image fields | no | `NO_IMAGE_VALID` |
| Bad or unaligned entry point | no | `BAD_ENTRY` |
| IMAGE_VALID, no BOOT_ATTEMPT, no APP_CONFIRMED | no | `FIRST_BOOT_REQUIRES_BOOT_ATTEMPT_WRITE` |
| IMAGE_VALID, BOOT_ATTEMPT, no APP_CONFIRMED | no | `WAIT_APP_CONFIRM` |
| IMAGE_VALID, BOOT_ATTEMPT, APP_CONFIRMED | yes | `APP_CONFIRMED` |

## Deferred

1. GUI wait window.
2. Automatic App jump.
3. `BOOT_ATTEMPT` write.
4. `APP_CONFIRMED` write.
5. flash_lib ready detection.
6. descriptor/header last-write rule.
7. watchdog recovery.
8. RESET command.
9. CPU2 / W5300 / GUI changes.

flash_lib ready detection and descriptor/header last-write rules are deferred
to Phase 10.6-B.
