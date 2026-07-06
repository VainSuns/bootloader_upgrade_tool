# Phase 10.6-C Slim Reset: Confirmed-only Auto-run

## Scope

This phase slims the Flash-resident bootloader back to a confirmed-only
automatic boot policy.

The Flash bootloader:

1. reads metadata;
2. waits for GUI/PC autobaud;
3. enters protocol mode if PC connects;
4. jumps App only after the GUI wait window times out and metadata proves the
   current image is confirmed.

It does not write metadata and does not attach retained flash_service_lib during
startup.

## Confirmed-only policy

Automatic jump is allowed only when all are true:

```text
metadata valid
IMAGE_VALID valid
BOOT_ATTEMPT exists for current IMAGE_VALID
APP_CONFIRMED exists for current IMAGE_VALID
entry point is inside the App Flash range
entry point is 8-word aligned
```

The removed first-trial path was:

```text
IMAGE_VALID valid
no BOOT_ATTEMPT
retained flash_lib ready
bootloader writes BOOT_ATTEMPT
jump App
```

That path is intentionally no longer compiled into the Flash bootloader.

## Startup flow

```text
scan metadata
confirmed_bootable = BootUser_IsConfirmedBootable(summary)
BootUser_CreateIoOpsTimeout(..., wait_forever = confirmed_bootable ? 0 : 1)

if connected:
    BootAlgorithm_Init
    BootAlgorithm_Run

if timeout and confirmed_bootable:
    BootUser_JumpToFlashApp(summary.entry_point)
```

If the current image is not confirmed, the bootloader waits forever for PC GUI
autobaud and never auto-jumps.

## Metadata ownership

Metadata writes are owned by downloaded flash_service_lib:

1. DFU writes IMAGE_VALID after Program + Verify.
2. PC RUN writes BOOT_ATTEMPT before jumping App.
3. `app_confirm_probe` writes APP_CONFIRMED after the user confirms App health.

The Flash bootloader startup path only reads metadata.

## APP_CONFIRM tool

`app_confirm_probe` performs:

```text
connect bootloader
descriptor-last load and attach flash_service_lib
GET_METADATA_SUMMARY
require IMAGE_VALID
require BOOT_ATTEMPT
append APP_CONFIRMED metadata
GET_METADATA_SUMMARY
verify app_confirmed
```

It does not send RUN.

## PC tool autobaud mode

The R&D CLI tools support:

```text
--autobaud-mode always
--autobaud-mode skip
```

Default is `always`.

## Still deferred

This phase does not add:

1. App self-confirm.
2. BootAppHandoff.
3. W5300.
4. CPU2 orchestration.
5. watchdog policy.
6. GUI changes.
7. static F021 in Flash bootloader.
8. static flash_service_lib in Flash bootloader.
9. Flash linker command expansion.
