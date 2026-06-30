# Phase 6 / Phase 7 Hardware Test Guide

## Purpose

This document describes the hardware regression tests used after the DSP bootloader core chain became functional.

These tests validate:

```text
Flash Program
Flash Verify
real .out conversion through hex2000
FirmwareImage workflow
Run App command
dynamic jump to Flash App
SCI TX behavior after removing per-word flush
```

## Hardware Assumptions

Target device:

```text
TMS320F28377D CPU1
```

Transport:

```text
SCI-A / RS232
GPIO64 = SCI-A RX
GPIO65 = SCI-A TX
```

Default test port:

```text
COM10
```

Default baudrate:

```text
9600
```

Flash app range:

```text
start: 0x082400
end:   0x0C0000 exclusive
```

Slot A metadata reservation:

```text
start: 0x082000
end:   0x082400 exclusive
```

`0x082000` is still the Flash B / Slot A region start. Test Apps must start at
`0x082400` so they do not occupy the metadata area.

Allowed erase mask:

```text
0x00003FFE
```

This means Sector A is protected and must not be erased by these tests.

## Important SCI Notes

The C2000 SCI TX FIFO depth is 16 bytes.

One bootloader protocol word is 16-bit and is transmitted as two bytes:

```text
low byte first
high byte second
```

Therefore:

```text
16-byte SCI FIFO = 8 protocol words maximum
```

The DSP SCI sender must ensure at least two byte slots are available before writing one protocol word.

Per-word flush is no longer used.

Flush is still required:

```text
after autobaud echo
before jumping to App
```

## Phase 6.1: Program / Verify Smoke Test

Purpose:

```text
Validate fixed small Flash Program / Verify using the protocol path.
```

Command:

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_1_program_verify_smoke.py --port COM10
```

Expected result:

```text
DeviceInfo OK
Erase Sector B OK
Program 8 words @ 0x082400 OK
Verify 8 words @ 0x082400 OK
PASS
```

Verify-only command:

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_1_program_verify_smoke.py --port COM10 --verify-only
```

Expected result:

```text
Verify 8 words @ 0x082400 OK
PASS
```

## Phase 6.2: FirmwareImage Workflow Test

Purpose:

```text
Validate FirmwareImage -> UpgradeWorkflow -> Program -> Verify.
```

Representative commands:

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_2_small_image_workflow_test.py --port COM10 --words 32
```

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_2_small_image_workflow_test.py --port COM10 --words 248
```

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_2_small_image_workflow_test.py --port COM10 --words 256
```

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_2_small_image_workflow_test.py --port COM10 --words 496
```

Additional padding boundary tests:

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_2_small_image_workflow_test.py --port COM10 --words 33
```

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_2_small_image_workflow_test.py --port COM10 --words 249
```

Verify-only persistence test:

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_2_small_image_workflow_test.py --port COM10 --words 496 --verify-only
```

Expected behavior:

```text
32 words    Program + Verify PASS
248 words   Program + Verify PASS
256 words   split as 248 + 8, Program + Verify PASS
496 words   split as 248 + 248, Program + Verify PASS
33 words    padded to 40, Program + Verify PASS
249 words   split as 248 + padded 8, Program + Verify PASS
verify-only PASS after reconnect/reset
```

## Phase 6.3: Real .out -> hex2000 -> Program / Verify

Purpose:

```text
Validate the real firmware conversion and upgrade path.
```

Validated chain:

```text
.out
  -> hex2000 -boot -a -sci8
  -> SCI8 parser
  -> FirmwareImage
  -> sector mask calculation
  -> Erase
  -> Program
  -> Verify
```

Dry-run command:

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_3_out_hex2000_workflow_test.py ^
  --port COM10 ^
  --out-file path\to\small_app.out ^
  --dry-run ^
  --keep-hex
```

Expected dry-run checks:

```text
hex2000 command succeeds
FirmwareImage is parsed
entry_point is inside [0x082400, 0x0C0000)
entry_point is 8-word aligned
blocks are inside app Flash range and do not occupy 0x082000-0x0823FF
calculated sector_mask does not include Sector A
calculated sector_mask is within 0x00003FFE
```

Program / Verify command:

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_3_out_hex2000_workflow_test.py ^
  --port COM10 ^
  --out-file path\to\small_app.out ^
  --keep-hex
```

Expected result:

```text
GET_DEVICE_INFO OK
Erase OK
Program OK
Verify OK
PASS
```

Verify-only command:

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_3_out_hex2000_workflow_test.py ^
  --port COM10 ^
  --out-file path\to\small_app.out ^
  --verify-only ^
  --keep-hex
```

Expected result:

```text
GET_DEVICE_INFO OK
Verify OK
PASS
```

## Phase 7.1: Run App Test

Purpose:

```text
Validate that the programmed Flash App can be launched by the bootloader.
```

Validated chain:

```text
PC sends RUN
DSP returns RUN OK response first
bootloader_core returns BOOT_ALGORITHM_ACTION_RUN_FLASH_APP
bootloader_user handles action
bootloader_user validates entry point
bootloader_user flushes SCI TX
bootloader_user jumps to Flash App
App starts running
```

Command:

```bat
".\.venv\Scripts\python.exe" .\tests\phase7\phase7_1_run_app_test.py ^
  --port COM10 ^
  --out-file path\to\small_app.out
```

Expected result:

```text
GET_DEVICE_INFO OK
RUN entry_point 0x00082400
RUN OK response received by PC
DSP jumps to LED App
LED blinks continuously
PASS
```

## Feature Flags Expected After DSP Reliability Patch

`GET_DEVICE_INFO` should advertise only:

```text
ERASE
PROGRAM
VERIFY
RUN
```

It must not advertise:

```text
RESET
RAM_LOAD
APP_UPLOAD
METADATA
UNLOCK_Z1
UNLOCK_Z2
```

GUI must follow `DeviceInfo.feature_flags`.

## Regression Sequence After SCI TX Changes

After changing SCI TX behavior, run:

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_1_program_verify_smoke.py --port COM10
```

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_2_small_image_workflow_test.py --port COM10 --words 249
```

```bat
".\.venv\Scripts\python.exe" .\tests\phase6\phase6_3_out_hex2000_workflow_test.py ^
  --port COM10 ^
  --out-file path\to\small_app.out ^
  --keep-hex
```

```bat
".\.venv\Scripts\python.exe" .\tests\phase7\phase7_1_run_app_test.py ^
  --port COM10 ^
  --out-file path\to\small_app.out
```

Acceptance criteria:

```text
No protocol response loss
No Program / Verify regression
RUN OK response is received before jump
LED App runs after RUN
```

## Troubleshooting

### RUN response not received

Check:

```text
BootUser_PrepareForAppJump() calls BootSci_Flush()
BootSci_SendWord() does not flush per word
SCI TX FIFO waits for at least 2 byte slots before writing one protocol word
PC receive path uses in_waiting polling
```

### Program / Verify fails after SCI TX optimization

Check:

```text
SCI FIFO handling uses byte count, not protocol word count
BootSci_WaitTxFifoSpace(2U) is used before writing low/high bytes
CRC and payload framing are unchanged
```

### RUN accepted but App does not run

Check:

```text
entry_point is correct
entry_point is 8-word aligned
entry_point is inside [0x082400, 0x0C0000)
BOOT_USER_FIXED_APP_ENTRY_ENABLE is 0 for dynamic entry mode
BootUser_JumpToEntryAsm is linked and disassembled correctly
App linker command places codestart / entry at or after 0x082400
```
