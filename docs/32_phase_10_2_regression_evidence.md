# Phase 10.2 Regression Evidence

## 1. Summary

| Area | Result | Notes |
|---|---|---|
| Full pytest | PASS | `108 passed in 6.65s` |
| Simulator workflow tests | PASS | `39 passed in 0.14s` |
| DSP host tests | PASS | GCC available; `3 passed in 0.71s` |
| GUI source-run simulator flow | NOT RUN | Manual GUI verification was not executed in this environment. |
| Packaging regression | FAIL | `tools/package_windows.ps1` failed before PyInstaller build. |
| Hardware HW-RG-01 | PENDING | Pending target-board execution. |
| Hardware HW-RG-02 | PENDING | Pending target-board execution. |
| Hardware HW-RG-03 | PENDING | Pending target-board execution. |
| Hardware HW-RG-04 | PENDING | Pending target-board execution. |

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
| HW-RG-01 Connect + DeviceInfo | No | N/A | F28377D CPU1 | SCI/RS232 | N/A | PENDING | Pending hardware execution. |
| HW-RG-02 Read blank metadata after Flash B erase | No | N/A | F28377D CPU1 | SCI/RS232 | N/A | PENDING | Pending hardware execution. |
| HW-RG-03 DFU writes IMAGE_VALID | No | N/A | F28377D CPU1 | SCI/RS232 | App linked at `0x082400` | PENDING | Pending hardware execution. |
| HW-RG-04 Run writes BOOT_ATTEMPT | No | N/A | F28377D CPU1 | SCI/RS232 | App linked at `0x082400` | PENDING | Pending hardware execution. |

## 6. Open Items

1. Fix or rerun Windows packaging regression; current run failed in `tools/package_windows.ps1`.
2. Execute GUI source-run Simulator DFU + Run verification.
3. Execute hardware HW-RG-01 through HW-RG-04 on target board.

## 7. Phase 10.2 Closure Decision

```text
FAIL: Phase 10.2 cannot be closed.
```

Reason:

1. Automated pytest, simulator workflow, and DSP host tests passed.
2. Packaging regression failed.
3. GUI source-run simulator regression was not executed.
4. Hardware HW-RG-01 through HW-RG-04 are pending.

No APP_CONFIRMED write path, automatic boot decision, or rollback was
implemented as part of this evidence phase.
