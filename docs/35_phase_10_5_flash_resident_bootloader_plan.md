# Phase 10.5 Flash-resident bootloader evidence

## Status

```text
Phase 10.5-A Extract App Layout: PASS
Phase 10.5-B Flash-resident bootloader project support: PASS
Phase 10.5-B Hardware validation: PASS
```

## Final conclusion

Flash-resident bootloader can boot from Flash, communicate over SCI, load and
attach the downloaded flash_service_lib, erase/program/verify the App image,
append IMAGE_VALID metadata, run the App, and produce the expected LED blinking
behavior.

## Boundary

1. `bootloader_cpu01_flash_lnk.cmd` is user-maintained.
2. Codex does not generate or modify the Flash linker cmd.
3. Flash-resident bootloader does not statically link flash_service_lib.
4. Flash-resident bootloader does not link F021 Flash API.
5. Flash erase/program/verify is still provided by downloaded flash_service_lib
   through SERVICE_ATTACH.
6. W5300 / CPU2 / GUI / A-B / Recovery / Security are not included in Phase
   10.5-B.

## Hardware validation conditions

```text
Bootloader mode: Flash-resident bootloader
Board: TMS320F28377D CPU1
Transport: SCI / RS232
COM: COM10
Baud: 9600
Service image: tests\phase10\flash_service_lib_cpu01.out
Service map: tests\phase10\flash_service_lib_cpu01.map
App image: tests\phase10\led_ex1_blinky_metadata.out
Sector mask: 0x00003FFE
Observable result: LED blinked normally after RUN
```

## Hardware acceptance

| ID | Item | Result | Evidence |
|---|---|---|---|
| HW-FB-01 | Flash-resident bootloader programmed | PASS | User confirmed test was executed with Flash bootloader. |
| HW-FB-02 | Reset / power-cycle into Flash bootloader | PASS | PC connected to bootloader over SCI. |
| HW-FB-03 | SCI connection | PASS | COM10 @ 9600. |
| HW-FB-04 | SERVICE_ATTACH downloaded flash_service_lib | PASS | service_attach_probe returned PASS. |
| HW-FB-05 | Service descriptor/API/CRC patch addresses | PASS | 0x13000 / 0x13020 / 0x13014. |
| HW-FB-06 | Service CRC and state | PASS | CRC32 0xD83B5ECB, state 2, version 0.1, capabilities 0x0000000F. |
| HW-FB-07 | Erase through attached service | PASS | service_flash_probe returned PASS. |
| HW-FB-08 | Program App | PASS | Program/Verify PASS. |
| HW-FB-09 | Verify App | PASS | Program/Verify PASS. |
| HW-FB-10 | Metadata IMAGE_VALID append | PASS | Metadata IMAGE_VALID PASS. |
| HW-FB-11 | RUN FLASH_APP | PASS | Run PASS, entry 0x00082400. |
| HW-FB-12 | Observable LED blink | PASS | LED blinked normally after RUN. |

## SERVICE_ATTACH evidence

Command:

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool.tools.service_attach_probe `
  --transport serial `
  --port COM10 `
  --baud 9600 `
  --image tests\phase10\flash_service_lib_cpu01.out `
  --map tests\phase10\flash_service_lib_cpu01.map `
  --hex2000 E:\CodeComposerStudio\CCS12.7\ccs\tools\compiler\ti-cgt-c2000_22.6.1.LTS\bin
```

Result:

```text
PASS: RAM image loaded, CRC checked, and SERVICE_ATTACH accepted
Descriptor address: 0x00013000
API table address: 0x00013020
CRC patch address: 0x00013014
Total words: 5800
Loaded CRC32: 0xD83B5ECB
Service state: 2
Service version: 0.1
Capabilities: 0x0000000F
```

## Full service Flash flow evidence

Command:

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool.tools.service_flash_probe `
  --transport serial `
  --port COM10 `
  --baud 9600 `
  --service-image tests\phase10\flash_service_lib_cpu01.out `
  --service-map tests\phase10\flash_service_lib_cpu01.map `
  --app-image tests\phase10\led_ex1_blinky_metadata.out `
  --sector-mask 0x00003FFE `
  --hex2000 E:\CodeComposerStudio\CCS12.7\ccs\tools\compiler\ti-cgt-c2000_22.6.1.LTS\bin `
  --run
```

Result:

```text
PASS: SERVICE_ATTACH + ERASE + PROGRAM + VERIFY completed

Service:
Descriptor address: 0x00013000
API table address: 0x00013020
CRC patch address: 0x00013014
Service words: 5800
Service CRC32: 0xD83B5ECB
Service state: 2
Service version: 0.1
Capabilities: 0x0000000F

App:
Image: tests\phase10\led_ex1_blinky_metadata.out
Entry point: 0x00082400
Total words: 3909
Sector mask: 0x00003FFE
Program/Verify: PASS
Metadata IMAGE_VALID: PASS
Run: PASS
```

Observable result:

```text
LED blinked normally after RUN.
```

## Deferred

No W5300, CPU2, GUI changes, A/B update, recovery, or security work is included
in Phase 10.5-B.
