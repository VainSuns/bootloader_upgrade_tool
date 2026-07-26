# Runtime V2 CPU1 GUI Hardware Validation Record

## Scope

```text
Target: TMS320F28377D CPU1
Transport: SCI-A / RS232
Repository HEAD: 5834c31e3be9f9e2c1379a075d4478ec22f5d64f
Validation date: 2026-07-26
Validation owner: user
Result: PASS
```

This file is hardware acceptance evidence. It is not an authority for the
current workflow, architecture, protocol, Flash layout, operation library, or
GUI specification. The applicable current contracts take precedence.

## Accepted implementation chain

| Commit | Accepted purpose |
|---|---|
| `582f5be17fb63f0693aab54a399453bd76425a4d` | Flash / Metadata operation progress |
| `73221d3e4fc85119e26b430c14f412628160bf14` | Controller stage progress reset |
| `4275f25f0ed45fc6a9029bc33e6f1e2c328a32de` | Run Flash App from fresh IMAGE_VALID Metadata |
| `5834c31e3be9f9e2c1379a075d4478ec22f5d64f` | APP_CONFIRMED and Flash Service progress |

## Observed hardware result

The user reported PASS for:

- CPU1 Runtime V2 GUI connection;
- Flash Service load, attach, and reuse;
- erase, program, and verify;
- IMAGE_VALID, BOOT_ATTEMPT, APP_CONFIRMED, and metadata readback;
- Run Flash App and confirmed App boot behavior;
- RAM Load, CRC, and Run;
- memory and freshness handling;
- runtime evidence invalidation;
- operation progress reporting.

The accepted Run Flash App behavior was:

```text
Prerequisite: fresh valid IMAGE_VALID
BOOT_ATTEMPT required: NO
APP_CONFIRMED required: NO
confirmed_bootable required: NO
Protocol behavior: one RUN command
Success behavior: release the PC connection
```

The accepted APP_CONFIRMED and Flash Service behavior was:

- APP_CONFIRMED uses the downloaded Flash Service;
- the APP_CONFIRMED command and payload were unchanged;
- APP_CONFIRMED Metadata progress advances from `0/64` to `64/64`;
- the first Flash Service load reports determinate progress;
- Flash Service reuse does not emit fake load progress.

## Evidence boundary

Codex did not execute hardware operations. The user performed and observed all
hardware operations. Raw serial logs and screenshots are not committed. Build
IDs, image paths, board identity, and local connection settings remain in
user-owned local records.

## Deferred scope

This record does not validate or close:

- CPU2 Runtime V2;
- CPU2 Bootloader;
- W5300/TCP transport;
- production GUI Reset;
- future watchdog hardening;
- future packaging/release work.

Full pytest was not run or claimed by this record. This record does not claim
completion of the entire project.

## Final decision

```text
STAGE_7A_SOFTWARE_GATE = PASS
USER_HARDWARE_VALIDATION_GATE = PASS
CPU1_RUNTIME_V2_GUI_HARDWARE_VALIDATION = PASS
CURRENT_CPU1_GUI_HOTFIX_BATCH = CLOSED
VALIDATED_HEAD = 5834c31e3be9f9e2c1379a075d4478ec22f5d64f
BLOCKING_ITEMS = NONE
```
