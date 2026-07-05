# Phase 10.5-D Flash bootloader slimming and redundancy cleanup

## Reason

Flash-resident bootloader hardware validation passed, but the current
BOOT_FLASH_CODE usage is already close to the next feature-risk threshold.

| Build | BOOT_FLASH_CODE Used | Total | Usage |
|---|---:|---:|---:|
| Before slimming | 6632 | 8190 | 80% |
| After slimming | TBD | 8190 | TBD |

The after-slimming value is intentionally left as TBD until the user rebuilds
in CCS and checks the linker map.

## Boundaries

This cleanup does not modify:

1. `bootloader_cpu01_flash_lnk.cmd`
2. `F2837xD_SysCtrl.c`
3. `F2837xD_Gpio.c`

This cleanup does not add W5300, CPU2, GUI, A/B update, recovery, security,
static flash_service_lib, or F021 Flash API into the bootloader.

## Changes

1. Added `boot_user_feature_config.h`.
2. Flash bootloader defaults `BOOT_ENABLE_RUN_RAM` to disabled.
3. Flash bootloader defaults `BOOT_ENABLE_RESET_COMMAND` to disabled.
4. `FLASH_READ` metadata and `GET_METADATA_SUMMARY` remain enabled for Phase
   10.6 preparation.
5. Split metadata implementation into:
   - `boot_metadata_scan.c`
   - `boot_metadata_build.c`
6. Flash bootloader project copies only `boot_metadata_scan.c`.
7. RAM bootloader project enables `BOOT_ENABLE_RUN_RAM=1`.
8. downloaded flash_service_lib project copies both metadata scan and build
   files.

## Preserved architecture

Flash erase/program/verify remains provided by downloaded flash_service_lib
attached through SERVICE_ATTACH.

## Next check

If BOOT_FLASH_CODE is still too tight after rebuilding, the user should evaluate
minimal SysCtrl/Gpio replacement separately with map evidence.
