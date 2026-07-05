# Phase 10.6-C R&D Auto Boot Closed Loop

## Scope

This phase enables the R&D automatic boot closed loop for the Flash-resident
bootloader without statically linking F021 or flash_service_lib into the
bootloader image.

Power-on / reset behavior:

```text
Flash bootloader hardware init
-> GUI/PC autobaud wait window
-> if GUI connects: stay in protocol mode
-> if GUI does not connect: evaluate boot decision
-> if decision allows: jump App
-> otherwise: stay in protocol mode
```

## GUI/PC wait window

The Flash bootloader project defines:

```c
BOOT_USER_AUTO_BOOT_ENABLE=1
```

The default wait window is configurable through:

```c
BOOT_USER_GUI_WAIT_WINDOW_MS
```

RAM development builds keep the default behavior unless the macro is explicitly
enabled.

## Allowed automatic jump cases

Only two cases may jump automatically.

### Case 1: first trial

```text
IMAGE_VALID valid
AND no BOOT_ATTEMPT
AND retained flash_lib ready
AND BOOT_ATTEMPT write success
-> jump App
```

If the retained flash_lib is not ready, or BOOT_ATTEMPT cannot be written, the
bootloader stays in protocol mode.

### Case 2: confirmed app

```text
IMAGE_VALID valid
AND BOOT_ATTEMPT exists
AND APP_CONFIRMED valid
-> jump App
```

This path does not require flash_lib ready because it does not write Flash.

## Retained flash_lib ready detection

The bootloader validates the retained service descriptor at:

```c
BOOT_USER_SERVICE_DESCRIPTOR_ADDRESS
```

The retained descriptor attach path checks descriptor magic, version,
descriptor size, descriptor CRC, ABI, API table address, image range, RAM
range, metadata-write capability, service API magic/ABI/size, and the retained
image CRC.

Because Phase 10.6-B1 uses descriptor-last loading, the retained RAM CRC is
reproduced in descriptor-last receive order:

```text
image_start ... descriptor_address - 1
descriptor_address + descriptor_words ... image_end_exclusive - 1
descriptor_address ... descriptor_address + descriptor_words - 1
```

The calculated CRC must match descriptor `image_crc32`.

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

## Still deferred

This phase does not add:

1. CPU2 boot.
2. W5300.
3. full GUI auto-boot controls.
4. static F021 in Flash bootloader.
5. static flash_service_lib in Flash bootloader.
6. production watchdog/rollback policy.
