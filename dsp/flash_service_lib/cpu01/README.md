# flash_service_lib CPU1 RAMGS CCS Project

This folder contains a CCS executable project skeleton for building a
RAM-loadable `flash_service_lib` image:

```text
flash_service_lib_cpu1.out
flash_service_lib_cpu1.map
```

No generated `.out`, `.map`, `.obj`, `.lib`, `.hex`, or `.txt` artifact should
be committed.

## User flow

1. Import `flash_service_lib_cpu01.projectspec` into CCS.
2. Build the project with CGT `22.6.1.LTS`.
3. Inspect the linker map.
4. Convert the `.out` with `hex2000`.
5. Use the PC tool to patch descriptor/API/CRC-patch addresses.
6. Download with `RAM_LOAD`.
7. Validate with `RAM_CHECK_CRC`.
8. Attach with `SERVICE_ATTACH`.

Do not use `RUN_RAM` for this service image.

## Fixed RAMGS layout

Temporary RAMGS7-RAMGS9 service image range:

```text
0x013000 - 0x015FFF
```

Fixed service header addresses:

```text
descriptor: 0x013000
crc patch : 0x013014
api table : 0x013020
code start: 0x013080
```

The linker map should show:

```text
.flash_service_descriptor at 0x013000
.flash_service_crc_patch  at 0x013014
.flash_service_api        at 0x013020
```

LOAD and RUN addresses are the same because the PC writes directly to RAMGS.

RAMGS7-RAMGS9 ownership must be configured so CPU1 can access the image before
hardware `SERVICE_ATTACH` testing.
