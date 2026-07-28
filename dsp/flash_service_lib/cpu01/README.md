# flash_service_lib CPU1 RAMGS CCS Project

This folder contains the CCS project skeleton for the CPU1 RAM-loadable
`flash_service_lib` image:

```text
flash_service_lib_cpu1.out
flash_service_lib_cpu1.map
```

No generated `.out`, `.map`, `.obj`, `.lib`, `.hex`, or `.txt` artifact should
be committed.

## User flow

1. Import `flash_service_lib_cpu01.projectspec` into CCS.
2. Build with CGT `22.6.1.LTS`.
3. Inspect the linker map as described below.
4. Stop and provide the `.map` for Header/image preparation review.

Batch 01A does not provide the PC Header patcher or Bootloader integration.
Do not use `RUN_RAM` for this service image.

## Fixed RAMGS layout

The CPU1 service image keeps the existing `0x3000`-word RAMGS7-RAMGS9
envelope:

```text
0x013000-0x01301F  Header reserved (0x20 words; structure is 28 words)
0x013020-0x013021  Publish State
0x013022-0x01305F  private Runtime State reserved
0x013060-0x01307F  fixed front reserved
0x013080-0x013081  App Export (immutable range start)
0x013082-0x015AFF  immutable code, ramfunc, and constants
0x015B00-0x015FFF  mutable data
```

The total envelope remains `0x013000-0x015FFF` (end exclusive `0x016000`).
LOAD and RUN addresses are identical because the PC writes directly to RAMGS.

## Map review

Confirm these sections and symbols:

```text
.flash_service_header        0x013000  g_boot_flash_service_header
.flash_service_publish_state 0x013020  g_boot_flash_service_publish_state
.flash_service_runtime_state 0x013022  private g_service storage
.flash_service_app_export    0x013080  g_boot_flash_service_app_export

BootFlashService_BootInit
BootFlashService_BootHandleCommand
BootFlashService_ConfirmCurrentImage
```

Also confirm that the Header section does not exceed `0x20` words, Runtime
State does not exceed `0x3E` words, App Export is exactly one C28x function
pointer (`0x02` words), immutable content ends before `0x015B00`, and all
non-fixed writable data is at or above `0x015B00`.

The Header function pointers and App Export function pointer come from the C
initializers and linker. Later PC preparation must preserve them. All other
Header fields remain unpatched placeholders in this Batch.

RAMGS7-RAMGS9 ownership must be configured so CPU1 can access the image before
later hardware integration.
