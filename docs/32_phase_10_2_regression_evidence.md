# Phase 10.2 Regression Evidence

## 1. Summary

| Area | Result | Notes |
|---|---|---|
| Full pytest | PASS | Latest rerun: `118 passed in 6.70s` |
| Simulator workflow tests | PASS | `39 passed in 0.14s` |
| DSP host tests | PASS | GCC available; `3 passed in 0.71s` |
| Metadata probe CLI | PASS | Added read-only CLI; `9 passed in 0.07s`; simulator probe smoke passed. |
| GUI source-run simulator smoke | OPTIONAL / NOT RUN | GUI manual smoke was not executed; metadata validation is covered by workflow tests and metadata_probe. |
| Packaging regression | PASS | Fixed in Phase 10.2M; one-folder package generated and packaged exe launch smoke passed. |
| Packaged GUI simulator smoke | OPTIONAL / NOT RUN | Packaged GUI launch smoke passed; simulator mode/DFU+Run manual smoke was not executed. |
| Hardware HW-RG-01 | PASS | Connect + DeviceInfo passed on F28377D CPU1 over COM10 at 9600 baud. |
| Hardware HW-RG-02 | PASS | Blank metadata read passed; metadata area read as erased. |
| Hardware HW-RG-03 | PASS | GUI DFU wrote IMAGE_VALID metadata. |
| Hardware HW-RG-04 | PASS | Run wrote BOOT_ATTEMPT metadata. |

## 2. Automated Test Evidence

Environment summary:

```text
Date/time: 2026-07-02 23:06:56 +08:00 through 2026-07-02 23:07:29 +08:00
Workspace: D:\Codes\DSP28377D\bootloader_upgrade_tool
Python: 3.12.13
GCC: gcc.exe (x86_64-win32-seh-rev0, MinGW-W64) 8.1.0
```

### 2.1 Full pytest

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result:

```text
108 passed in 6.65s
Skipped: 0 reported
Failures: none
```

### 2.2 Simulator Workflow Tests

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_simulator_workflow.py -q
```

Result:

```text
39 passed in 0.14s
Skipped: 0 reported
Failures: none
```

Covered simulator scenarios:

1. DFU appends IMAGE_VALID.
2. Failed Verify does not append IMAGE_VALID.
3. Metadata append before Verify is rejected.
4. Repeated IMAGE_VALID append after one Verify is rejected.
5. BOOT_ATTEMPT append before IMAGE_VALID is rejected.
6. `workflow.run()` appends BOOT_ATTEMPT before RUN.
7. Direct RUN without BOOT_ATTEMPT is rejected.
8. Run without metadata is rejected.
9. Run entry mismatch is rejected.
10. Attempt limit reached is rejected.
11. FLASH_READ metadata bounds are enforced.
12. GET_METADATA_SUMMARY reports expected fields.
13. APP_CONFIRMED remains unsupported.

### 2.3 DSP Host Tests

Command:

```powershell
gcc --version
.\.venv\Scripts\python.exe -m pytest tests/unit/test_dsp_host.py -q
```

Result:

```text
GCC available: yes
GCC version: gcc.exe (x86_64-win32-seh-rev0, MinGW-W64) 8.1.0
DSP host tests compiled: yes
DSP host tests passed: yes
3 passed in 0.71s
Skipped: 0 reported
Failures: none
```

Covered DSP host areas:

1. Protocol CRC16.
2. Byte-level magic resync.
3. Metadata parser/scanner.
4. IMAGE_VALID record builder.
5. BOOT_ATTEMPT record builder.
6. Service command forwarding.
7. RUN metadata validation.
8. Flash service verify gate behavior.

## 3. GUI Source-Run Evidence

Result:

```text
NOT RUN
```

Manual GUI source-run simulator verification was not executed in this
environment. Do not count GUI source-run regression as passed until the GUI is
launched and the documented Simulator DFU + Run flow is verified.

## 4. Packaging Evidence

Command:

```powershell
.\tools\package_windows.ps1
```

Date/time:

```text
2026-07-02 23:07:45 +08:00
```

Result:

```text
FAIL
```

Failure detail:

```text
tools\package_windows.ps1:29
Invoke-Native $Python -m pip install -e ".[packaging]"
Parameter cannot be processed because the parameter name 'e' is ambiguous.
Possible matches include: -ErrorAction -ErrorVariable.
```

Packaging status:

1. Package build executed: yes.
2. One-folder package generated: no evidence from this run.
3. Packaged GUI launched: not executed.
4. Simulator mode in packaged GUI: not executed.
5. hex2000 external/not bundled: not verified in this run.

## 5. Hardware Regression Evidence

| Check | Executed | Date/time | Board / target | Connection | App image | Result | Notes |
|---|---|---|---|---|---|---|---|
| HW-RG-01 Connect + DeviceInfo | Yes | 2026-07-04 | F28377D CPU1 | SCI/RS232 COM10 @ 9600 | N/A | PASS | DeviceInfo read: Device ID `0x377D`, CPU ID `1`. |
| HW-RG-02 Read blank metadata after Flash B erase | Yes | 2026-07-04 | F28377D CPU1 | SCI/RS232 COM10 @ 9600 | N/A | PASS | `metadata_valid: 0`; first 64 metadata words read as `0xFFFF`. |
| HW-RG-03 DFU writes IMAGE_VALID | Yes | 2026-07-04 | F28377D CPU1 | SCI/RS232 COM10 @ 9600 | App linked at `0x082400` | PASS | `latest_record_type: IMAGE_VALID`, `boot_attempt_count: 0`, `image_crc32: 0x774A5B7E`. |
| HW-RG-04 Run writes BOOT_ATTEMPT | Yes | 2026-07-04 | F28377D CPU1 | SCI/RS232 COM10 @ 9600 | App linked at `0x082400` | PASS | `latest_record_type: BOOT_ATTEMPT`, `boot_attempt_count: 1`. |

## 6. Open Items

1. Optional: execute GUI source-run simulator smoke test.
2. Optional: execute packaged GUI simulator smoke test.
3. Optional: repeat HW-RG-01 through HW-RG-04 using metadata_probe over serial after hardware or image changes.

## 7. Phase 10.2 Closure Decision

```text
PASS: Phase 10.2 hardware acceptance is complete. Automated tests, metadata_probe, simulator workflow tests, DSP host tests, packaging regression, and target-board hardware metadata evidence have passed.
```

Reason:

1. Automated pytest, simulator workflow, and DSP host tests passed.
2. Packaging regression has been fixed and rerun successfully.
3. GUI source-run simulator smoke remains optional for metadata validation.
4. Hardware HW-RG-01 through HW-RG-04 passed on target board.

No APP_CONFIRMED write path, automatic boot decision, or rollback was
implemented as part of this evidence phase.

## 8. Phase 10.2M Packaging Regression Fix Evidence

### 8.1 Root Cause

The original packaging failure had two parts:

1. PowerShell parsed bare `-e` in `Invoke-Native $Python -m pip install -e ".[packaging]"` as an ambiguous PowerShell parameter instead of forwarding it to pip.
2. After fixing argument forwarding, pip build isolation attempted to fetch build dependencies from the configured package index and failed in this restricted environment.

### 8.2 Fix

Changed file:

```text
tools/package_windows.ps1
```

Fix summary:

```text
1. Forward native command arguments using explicit string arrays.
2. Use --no-build-isolation for editable packaging install so the script reuses the current venv build backend.
```

The fixed install call is:

```powershell
Invoke-Native $Python @("-m", "pip", "install", "--no-build-isolation", "-e", ".[packaging]")
```

### 8.3 Packaging Rerun

Command:

```powershell
.\tools\package_windows.ps1
```

Date/time:

```text
2026-07-02 23:19:25 +08:00
```

Result:

```text
PASS
```

Evidence:

```text
Portable build created: D:\Codes\DSP28377D\bootloader_upgrade_tool\dist\DSP28377D_Bootloader_Upgrade_Tool
dist_exists=True
exe_exists=True
hex2000_count=0
```

Packaged GUI launch smoke:

```text
2026-07-02 23:20:15 +08:00
RUNNING pid=7408
STOPPED
```

The packaged GUI process started and remained running for the smoke window, then
the test process was stopped. Simulator mode inside the packaged GUI was not
manually verified in this run.

### 8.4 Automated Regression Rerun

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Date/time:

```text
2026-07-02 23:18:27 +08:00
```

Result:

```text
108 passed in 6.67s
```

### 8.5 Updated Closure Decision

```text
SUPERSEDED BY PHASE 10.2O: Packaging fixed and automated tests passed; hardware evidence was completed later in Phase 10.2O.
```

Phase 10.2 final closure is recorded in Phase 10.2O.

## 9. Phase 10.2N Metadata Probe CLI + Final Manual Evidence

### 9.1 metadata_probe CLI Implementation

Record:

- CLI module path: `pc/src/bootloader_upgrade_tool/tools/metadata_probe.py`
- Supported transports: `simulator`, `serial`
- Read-only guarantee: the CLI only calls `ping()`, `get_device_info()`,
  `get_metadata_summary()`, optional `flash_read_metadata()`, and close.
- Not called by the CLI: metadata append, erase, program, verify, DFU, run,
  reset.
- Tests added: `tests/unit/test_metadata_probe.py`
- Simulator CLI smoke: passed with `--transport simulator --raw-words 4`.

### 9.2 metadata_probe Automated Tests

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_metadata_probe.py -q
```

Result:

```text
PASS
9 passed in 0.07s
```

### 9.3 Full Regression Rerun

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result:

```text
PASS
118 passed in 6.70s
```

### 9.4 metadata_probe Simulator Smoke

Command:

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool.tools.metadata_probe --transport simulator --raw-words 4
```

Result:

```text
PASS
```

Evidence:

```text
Device:
  target_device_id: 0x377D
  target_cpu_id: 1
  protocol_version: 0x0001
  max_payload_words: 256
  max_data_words: 248

Metadata Summary:
  metadata_valid: 0
  active_slot: NONE
  latest_record_type: NONE
  boot_attempt_count: 0
  boot_attempt_limit: 3
  app_confirmed: 0
  entry_point: 0x00000000
  image_size_words: 0
  image_crc32: 0x00000000
  app_version: 0.0.0.0
  target_device_id: 0x0000
  target_cpu_id: 0
  state: 0
  valid_record_count: 0
  invalid_record_count: 0
  erased_record_count: 16
  free_record_count: 16
  next_record_index: 0

Raw Metadata:
  0x00082000: 0xFFFF 0xFFFF 0xFFFF 0xFFFF
```

Note: this simulator CLI probe starts a fresh in-process simulator. If the GUI
is running in a separate process, simulator state is not shared between GUI and
`metadata_probe`; hardware `metadata_probe` remains the primary manual metadata
evidence path after GUI hardware DFU + Run.

### 9.5 GUI Source-Run Simulator Evidence

Result:

```text
OPTIONAL / NOT RUN
```

This check is optional smoke evidence in Phase 10.2N-1. It verifies that the
GUI can still launch and drive DFU + Run, but it is not used as the primary
metadata validation path because the GUI does not expose metadata summary or
raw metadata read.

Evidence:

```text
Date/time: N/A
App .out path or name: N/A
Entry point shown by GUI: N/A
Calculated sector mask: N/A
DFU result: N/A
Run result: N/A
Notes: User/operator manual GUI source-run simulator verification has not been provided.
```

### 9.6 Packaged GUI Simulator Evidence

Result:

```text
OPTIONAL / NOT RUN
```

Packaged GUI launch smoke passed in Phase 10.2M. Packaged Simulator DFU + Run
remains optional manual smoke evidence and is not required for metadata
validation.

Evidence:

```text
Date/time: N/A
Packaged exe path: dist\DSP28377D_Bootloader_Upgrade_Tool\DSP28377D_Bootloader_Upgrade_Tool.exe
GUI launched: launch smoke passed in Phase 10.2M, but manual GUI verification was not executed.
Simulator mode available: not verified.
DFU + Run executed: no.
Result and notes: User/operator packaged GUI simulator verification has not been provided.
```

### 9.7 Hardware Metadata Evidence

| Check | Result | Date/time | Board / target | Connection | App image | Probe result | Notes |
|---|---|---|---|---|---|---|---|
| HW-RG-01 Connect + DeviceInfo | PASS | 2026-07-04 | F28377D CPU1 | SCI/RS232 COM10 @ 9600 | N/A | Device ID `0x377D`, CPU ID `1` | DeviceInfo was successfully read. |
| HW-RG-02 Blank metadata read | PASS | 2026-07-04 | F28377D CPU1 | SCI/RS232 COM10 @ 9600 | N/A | `metadata_valid: 0`; raw words erased | Blank metadata read passed. |
| HW-RG-03 DFU writes IMAGE_VALID | PASS | 2026-07-04 | F28377D CPU1 | SCI/RS232 COM10 @ 9600 | App linked at `0x082400` | `latest_record_type: IMAGE_VALID` | DFU wrote IMAGE_VALID metadata. |
| HW-RG-04 Run writes BOOT_ATTEMPT | PASS | 2026-07-04 | F28377D CPU1 | SCI/RS232 COM10 @ 9600 | App linked at `0x082400` | `latest_record_type: BOOT_ATTEMPT`, `boot_attempt_count: 1` | Run wrote BOOT_ATTEMPT metadata. |

### 9.8 Final Phase 10.2 Closure Decision

```text
PASS: Phase 10.2 hardware acceptance is complete. Automated tests, metadata_probe, simulator workflow tests, DSP host tests, packaging regression, and target-board hardware metadata evidence have passed.
```

Reason:

1. `metadata_probe` CLI exists and automated tests pass.
2. Full pytest regression passes.
3. Simulator workflow tests already cover DFU IMAGE_VALID, BOOT_ATTEMPT,
   metadata-aware Run, and negative paths.
4. GUI has no metadata display page, so GUI manual smoke is optional for Phase
   10.2 metadata validation.
5. Packaged GUI launch smoke already passed in Phase 10.2M; packaged simulator
   DFU+Run remains optional manual smoke.
6. Hardware HW-RG-01 through HW-RG-04 passed with metadata_probe over serial.
7. No GUI metadata page, APP_CONFIRMED implementation, automatic boot decision,
   or rollback was added.

No GUI metadata page, APP_CONFIRMED implementation, automatic boot decision, or
rollback was added.

## 10. Phase 10.2O Hardware Acceptance Evidence

### 10.1 Hardware Setup

```text
Target: F28377D CPU1
Connection: SCI/RS232
COM port: COM10
Baud: 9600
Device ID: 0x377D
CPU ID: 1
App entry point: 0x00082400
```

### 10.2 HW-RG-01 Connect + DeviceInfo

Result:

```text
PASS
```

Evidence:

```text
COM: COM10
Baud: 9600
Device ID: 0x377D
CPU ID: 1
```

Note: the user-provided heading contained "PASS / FAIL", but DeviceInfo was
successfully read and later metadata_probe operations over the same serial path
succeeded. HW-RG-01 is recorded as PASS.

### 10.3 HW-RG-02 Blank metadata read

Result:

```text
PASS
```

Evidence:

```text
metadata_valid: 0

Raw Metadata:
  0x00082000: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF
  0x00082008: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF
  0x00082010: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF
  0x00082018: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF
  0x00082020: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF
  0x00082028: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF
  0x00082030: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF
  0x00082038: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF
```

### 10.4 HW-RG-03 DFU writes IMAGE_VALID

Result:

```text
PASS
```

Evidence:

```text
latest_record_type: IMAGE_VALID
boot_attempt_count: 0
entry_point: 0x00082400
image_crc32: 0x774A5B7E
```

Raw Metadata:

```text
  0x00082000: 0x4D42 0x4453 0x0001 0x0040 0x0001 0x0001 0x0000 0x0001
  0x00082008: 0x0001 0x0000 0x2400 0x0008 0x0240 0x0009 0x2400 0x0008
  0x00082010: 0x0F58 0x0000 0x5B7E 0x774A 0x0000 0x0000 0x0000 0x0000
  0x00082018: 0x0000 0x377D 0x0001 0x0003 0x0000 0xFFFF 0xFFFF 0xFFFF
  0x00082020: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF
  0x00082028: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF
  0x00082030: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF
  0x00082038: 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xFFFF 0xE83D 0x5176
```

### 10.5 HW-RG-04 Run writes BOOT_ATTEMPT

Result:

```text
PASS
```

Evidence:

```text
latest_record_type: BOOT_ATTEMPT
boot_attempt_count: 1
entry_point: 0x00082400
```

Important evidence note: the raw metadata dump shown for HW-RG-04 only includes
the first 64 words at `0x082000`, which correspond to the first metadata
record, IMAGE_VALID. BOOT_ATTEMPT is append-only and is expected to be in the
next metadata record slot starting at `0x082040`. Therefore the raw dump may
look identical to HW-RG-03 if only the first 64 words are read.

The metadata summary is the primary evidence for HW-RG-04 and reports:

```text
latest_record_type = BOOT_ATTEMPT
boot_attempt_count = 1
```

This is sufficient to mark HW-RG-04 as PASS.

### 10.6 Final Closure Decision

```text
PASS: Phase 10.2 hardware acceptance is complete. Automated tests, metadata_probe, simulator workflow tests, DSP host tests, packaging regression, and target-board hardware metadata evidence have passed.
```

## 11. Phase 10.3 Follow-up

Phase 10.3 RAM_LOAD + RAM_CHECK_CRC + RUN_RAM evidence is tracked separately in
`docs/33_phase_10_3_ram_load_run_evidence.md`.
