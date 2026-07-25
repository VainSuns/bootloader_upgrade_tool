# Runtime V2 CPU1 GUI Hardware Validation Guide

## 1. Purpose and authority

This guide is the user-executed hardware gate after Runtime V2 Stage 7A
focused software acceptance. Codex stops before hardware access and does not
connect to the board.

This operational guide does not override RAC-V2, the communication protocol,
the operation-library contract, TargetProfile data, or Flash-layout contracts.

Scope exclusions:

- CPU1 functionality is completed and validated first. CPU2 is not part of
  this Stage 7A hardware validation and remains deferred for later migration
  and adaptation.
- W5300/TCP is an optional transport reserved for the final development stage.
  It is not part of this Stage 7A hardware validation. If space is
  insufficient, optimize first; if it remains insufficient, W5300 may be
  canceled.
- This guide does not simulate, fabricate, or claim hardware validation for
  CPU2 or W5300/TCP.

Hardware baseline:

```text
Target: TMS320F28377D CPU1
Transport: SCI-A / RS232
GPIO64: SCI-A RX
GPIO65: SCI-A TX
Control: PC master / DSP slave
SCI word order: low byte, then high byte
Autobaud: PC sends ASCII 'A'; DSP echoes ASCII 'A'
```

Do not replace the placeholders below until the user confirms the actual
artifacts and connection settings:

```text
<COM_PORT>
<BAUDRATE>
<BOOTLOADER_BUILD_ID>
<FLASH_SERVICE_BUILD_ID>
<APP_OUT_FILE>
<RAM_APP_OUT_FILE>
```

## 2. Software prerequisite gate

For this two-file Qt/Controller check only, first confirm no earlier repository
`.venv` Python process remains. If a previous run was interrupted or timed out,
do not start a replacement process until the old one exits. Clear repository
pytest and Python bytecode caches without modifying `.venv`, verify no
repository caches remain, then run the two approved files in a fresh Python
process:

```powershell
$repoPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
$repoPythonProcesses = @(
    Get-Process python, pythonw -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $repoPython }
)
if ($repoPythonProcesses.Count -ne 0) {
    $repoPythonProcesses | Select-Object Id, ProcessName, Path, StartTime
    throw "A previous repository Python process is still running"
}

$repoRoot = (Get-Item -LiteralPath .).FullName.TrimEnd('\')
$venvRoot = (Get-Item -LiteralPath .venv).FullName.TrimEnd('\')
$cacheDirs = @(
    Get-ChildItem -LiteralPath $repoRoot -Recurse -Directory -Force |
        Where-Object {
            $_.Name -in @('.pytest_cache', '__pycache__') -and
            -not $_.FullName.StartsWith(
                $venvRoot + '\',
                [System.StringComparison]::OrdinalIgnoreCase
            )
        }
)
$cacheDirs | Remove-Item -Recurse -Force

$remainingCaches = @(
    Get-ChildItem -LiteralPath $repoRoot -Recurse -Directory -Force |
        Where-Object {
            $_.Name -in @('.pytest_cache', '__pycache__') -and
            -not $_.FullName.StartsWith(
                $venvRoot + '\',
                [System.StringComparison]::OrdinalIgnoreCase
            )
        }
)
if ($remainingCaches.Count -ne 0) {
    $remainingCaches.FullName
    throw "Repository test caches remain"
}

$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONFAULTHANDLER = "1"

.\.venv\Scripts\python.exe -X faulthandler -m pytest `
  tests/unit/test_gui_controller.py `
  tests/unit/test_gui_advanced_metadata_controller.py `
  -q
```

Expected result:

```text
54 passed
exit code 0
fresh Python process
Full pytest: NOT REQUIRED for this Stage 7A baseline
```

Stop before hardware work if this focused gate fails, crashes, or hangs.
For repeated stability runs, repeat the repository process check before every
pytest invocation and require a count of zero; never overlap fresh processes.
Do not extend this special procedure to unrelated targeted tests.

## 3. Environment record

Record before connecting:

| Field | Value |
|---|---|
| Date | |
| PC OS | |
| Python version | |
| PySide6 version | |
| pytest version | |
| Repository branch | |
| Repository HEAD | |
| DSP bootloader build | `<BOOTLOADER_BUILD_ID>` |
| downloaded flash_lib build | `<FLASH_SERVICE_BUILD_ID>` |
| App build | `<APP_OUT_FILE>` |
| RAM App build | `<RAM_APP_OUT_FILE>` |
| COM port | `<COM_PORT>` |
| baudrate | `<BAUDRATE>` |
| board / hardware revision | |

## 4. CPU1 connection validation

1. Start the GUI from the accepted repository HEAD.
2. Select SCI/RS232 and CPU1.
3. Enter `<COM_PORT>` and `<BAUDRATE>`.
4. Connect and allow the SCI transport to perform autobaud.
5. Confirm DeviceInfo is shown and matches the expected device and CPU.
6. Confirm the active target is CPU1 and a connection generation exists.
7. Disconnect, reconnect, and confirm a new generation is established.

For each attempt record the result, GUI log, error code, and failing stage.

## 5. Program Image and resource validation

Responsibility boundary:

- The Flash-resident bootloader only reads metadata. It does not erase,
  program, or verify Flash, and it does not write metadata.
- The Flash-resident bootloader does not statically link the F021 Flash API or
  `flash_service_lib`.
- The downloaded `flash_lib` performs authorized metadata journal writes,
  including IMAGE_VALID, BOOT_ATTEMPT, and APP_CONFIRMED, and also performs
  Flash erase, Flash program, and Flash verify.

Flash Service descriptor chain:

1. The PC tool parses the `flash_lib` descriptor address from the selected map
   file or symbol information.
2. The PC supplies that descriptor address to the DSP through SERVICE_ATTACH.
3. The bootloader does not hardcode the descriptor address.
4. The bootloader validates the address range, descriptor structure, CRC, ABI
   compatibility, and required capabilities.
5. SERVICE_ATTACH remains internal operation-library behavior and is not
   exposed as an ordinary user workflow button.

1. Submit `<APP_OUT_FILE>` as the CPU1 Program Image.
2. Confirm automatic parsing displays entry point, word count, CRC32, and
   sector mask.
3. Confirm Advanced and the Backend snapshot show the same image summary.
4. Confirm the configured `hex2000.exe` path is valid for `.out` conversion.
5. Confirm the Flash Service map/symbol data supplies the descriptor address
   through PC-side parsing.
6. Confirm SERVICE_ATTACH is not exposed as an ordinary user button.

## 6. Flash plan confirmation

Validate each selectable erase scope:

```text
Required App Sectors
Entire Application Region
Custom Sector Mask
```

Confirm Sector A is visible but cannot be selected, and any forbidden sector
is rejected before a real operation. Before confirming a write, verify that
the dialog shows the target, connection generation, image identity, and sector
plan. No write may begin before explicit confirmation.

## 7. Flash operation chain

Execute and record these user actions separately:

```text
Erase
Program Only
Verify Only
Write IMAGE_VALID
```

Confirm:

- Erase, Program, and Verify use the downloaded `flash_lib`;
- Verify Only does not write IMAGE_VALID;
- Program Only does not Run;
- IMAGE_VALID is bound to the current App identity;
- metadata refresh succeeds after the write.

## 8. BOOT_ATTEMPT and APP_CONFIRMED

Validate:

- the first BOOT_ATTEMPT;
- repeated BOOT_ATTEMPT behavior and the allowed count/policy message;
- BOOT_ATTEMPT is bound to the current IMAGE_VALID record and the current image
  identity;
- APP_CONFIRMED is rejected without the current IMAGE_VALID;
- APP_CONFIRMED is rejected without a BOOT_ATTEMPT for the current image;
- APP_CONFIRMED is bound to the current IMAGE_VALID;
- after programming a new App, old BOOT_ATTEMPT and APP_CONFIRMED evidence
  cannot be reused.

`confirmed_bootable` is true only when all of these are true:

```text
metadata valid
AND IMAGE_VALID valid
AND current-image BOOT_ATTEMPT exists
AND current-image APP_CONFIRMED valid
AND entry point valid
```

## 9. Metadata refresh warning

The accepted simulated behavior for a successful primary metadata write
followed by a failed automatic readback is:

```text
Task final status: SUCCEEDED
warning: METADATA_REFRESH_FAILED
metadata freshness: STALE
connection: CONNECTED
previous snapshot: retained
```

Real hardware communication does not need to be deliberately damaged to
produce this condition. Record it as `software-simulated acceptance only`
unless it occurs naturally.
This warning-only failure path is covered by focused software tests. Real
hardware validation does not require intentionally interrupting SCI
communication or otherwise damaging the connection to reproduce it.

## 10. RAM chain

Submit `<RAM_APP_OUT_FILE>`, then execute separately:

```text
RAM Load
RAM CRC
RAM Run
```

Confirm Load is not Run; CRC Evidence is bound to the current RAM image and
connection generation; RAM Run is rejected without current CRC Evidence; Run
releases the connection; reconnecting invalidates old Evidence; and the
RUN_RAM / RAM_RUN source and capability remain available.

## 11. Memory and freshness

1. Read CPU1 Memory and confirm it is shown as fresh.
2. Change the connection and confirm retained data becomes stale.
3. Refresh manually and confirm new data becomes fresh.
4. Clear CPU1 data and confirm only the corresponding CPU/runtime data clears.
5. Confirm CPU2 is explicitly disabled or unavailable when not implemented.

## 12. Flash Run and confirmed auto-boot

Validate Run Flash App and confirm RUN does not implicitly write
BOOT_ATTEMPT. Confirm Run releases the connection.

After returning to the bootloader, verify separately:

- an unconfirmed image waits indefinitely for PC autobaud;
- a confirmed image provides the PC takeover window;
- expiry of that window automatically starts the App.

Codex does not execute or observe these steps.

Reset boundary:

- Reset is not executed by Codex and is not part of the automated Stage 7A
  software gate.
- When a hardware procedure requires a board or DSP reset, the user performs
  it explicitly according to the user's hardware setup.
- GUI Reset capability remains deferred and is not validated by this guide.

User observation boundary:

- LED blinking, App startup, SCI output, watchdog behavior, and other physical
  or externally observable App behavior can only be confirmed by the user.
- Codex must not claim PASS from an assumed LED or App result.

## 13. Evidence invalidation

Confirm:

- disconnect/reconnect changes the connection generation;
- old VerifyEvidence becomes invalid;
- old RamCrcEvidence becomes invalid;
- changing Program Image invalidates old VerifyEvidence;
- changing RAM Image invalidates old RamCrcEvidence;
- switching Session invalidates old Runtime evidence.

## 14. Failure report

For every failed or blocked item, record:

| Field | Value |
|---|---|
| Test item | |
| PASS / FAIL / BLOCKED | |
| Repository HEAD | |
| DSP build IDs | |
| Operation | |
| Stage | |
| Error code | |
| Error message | |
| GUI log excerpt | |
| Screenshot | |
| Reproduction steps | |
| Connection generation | |
| Target CPU | |
| Reset/reconnect behavior | |
| Flash result | |
| Metadata result | |
| RAM result | |

## 15. Hardware gate decision

```text
STAGE_7A_SOFTWARE_GATE = PASS
USER_HARDWARE_VALIDATION_GATE = PENDING
```

Codex must not close or report the hardware gate as PASS. Only after the user
completes the real hardware items in this guide and records the evidence may
`USER_HARDWARE_VALIDATION_GATE` become `PASS`.
