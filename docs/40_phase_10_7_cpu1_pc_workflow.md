# Phase 10.7 CPU1 PC Workflow Productization

## Scope

Phase 10.7 adds product-facing CPU1 PC command-line tools. It does not change
DSP code, protocol behavior, Flash service behavior, CPU2, W5300, or the
confirmed-only Flash bootloader policy.

## Tools

### cpu1_upgrade

Run as:

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool.tools.cpu1_upgrade <command> [options]
```

Commands:

```text
status
attach-service
flash
run
confirm
upgrade
```

`cpu1_upgrade` is for CPU1 Flash App upgrade only. It uses the existing
`SerialIoDevice`, `ProtocolClient`, and `UpgradeWorkflow` paths.

Common options:

```text
--transport serial
--port COMx
--baud 9600
--autobaud-mode always|skip
--timeout-ms <ms>
--output text|json
--json
```

`--json` is an alias for `--output json`.

Service options:

```text
--service-image <flash_service_lib .out or SCI8 TXT>
--service-map <flash_service_lib .map>
--service-descriptor-symbol g_boot_flash_service_descriptor
```

The descriptor address is parsed from the linker map. There is no hardcoded
descriptor-address fallback.

App options:

```text
--app-image <CPU1 App .out or SCI8 TXT>
--hex2000 <hex2000.exe path or compiler root>
--sci8-txt <path>
--keep-sci8-txt
--hex-file <path>
--keep-hex
--sector-mask <uint32>
```

`--hex-file` and `--keep-hex` are compatibility aliases. New text and JSON
output should call the generated file `SCI8 TXT`, not ordinary hex.

### cpu1_ram_run

Run as:

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool.tools.cpu1_ram_run --transport serial --port COM10 --image app_ram.out --hex2000 <path>
```

`cpu1_ram_run` is a separate RAM App quick-test path:

```text
RAM_LOAD -> RAM_CHECK_CRC -> RUN_RAM
```

It does not erase Flash, program Flash, verify Flash, load flash_service_lib,
write IMAGE_VALID, write BOOT_ATTEMPT, or write APP_CONFIRMED.

It supports:

```text
--transport serial|simulator
--baud 9600
--autobaud-mode always|skip
--image <.out or SCI8 TXT>
--sci8-txt <SCI8 TXT>
--hex-file <SCI8 TXT alias>
--keep-sci8-txt
--keep-hex
--output text|json
--json
```

RAM images use RAM validation rules. Flash App range checks and Flash 8-word
entry alignment rules are not applied to RAM App entry points.

## Flash App Safety Rules

Flash App upgrade commands validate:

1. entry point is inside Slot A App range;
2. entry point is 8-word aligned;
3. image blocks are inside Slot A App range;
4. image blocks do not write Slot A metadata;
5. sector mask is nonzero;
6. sector mask does not erase Sector A / bootloader;
7. sector mask covers the sectors touched by the image.

Slot A layout:

```text
metadata: 0x082000..0x0823FF
app:      0x082400..0x0BFFFF
```

## Confirmed-only Policy

Flash bootloader automatic boot remains confirmed-only:

```text
metadata valid
AND IMAGE_VALID valid
AND BOOT_ATTEMPT exists for current IMAGE_VALID
AND APP_CONFIRMED exists for current IMAGE_VALID
AND entry point valid
```

`cpu1_upgrade run` ensures the current `IMAGE_VALID` has a `BOOT_ATTEMPT`, then
sends `RUN FLASH_APP`. It does not append another `BOOT_ATTEMPT` if the current
image is already confirmed or already has an attempt.

`cpu1_upgrade confirm` requires a current `IMAGE_VALID` and a current
`BOOT_ATTEMPT`. It does not send `RUN`. It writes `APP_CONFIRMED` using the
current `GET_METADATA_SUMMARY` values:

```text
entry_point
image_size_words
image_crc32
```

After a new App is flashed, old `BOOT_ATTEMPT` and old `APP_CONFIRMED` records
must not be reused.

## One-shot Upgrade Notes

`cpu1_upgrade upgrade` performs:

```text
connect
parse App image
calculate App identity
GET_METADATA_SUMMARY / status
same_image check

if flash is needed:
    SERVICE_ATTACH
    Erase / Program / Verify
    write IMAGE_VALID

if run is needed:
    SERVICE_ATTACH only if BOOT_ATTEMPT must be written and service is not already attached
    write BOOT_ATTEMPT if needed
    RUN

APP_CONFIRM remains a separate confirm command
```

Options:

```text
--no-run
--no-confirm
--force
--dry-run
```

`upgrade` no longer writes `APP_CONFIRMED` by default. After the App has run
successfully, re-enter the bootloader and run:

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool.tools.cpu1_upgrade confirm --transport serial --port COM10 --service-image service.out --service-map service.map
```

## Deferred

Phase 10.7 does not implement:

1. W5300 / TCP;
2. CPU2;
3. new protocol frame formats;
4. new DSP boot policy;
5. Flash bootloader static F021 linkage;
6. Flash bootloader static flash_service_lib linkage;
7. GUI changes.
