# Phase 10.2 Regression Requirements

## 1. Regression Objective

Verify that Phase 10.2 metadata reliability changes do not break the existing
source-run MVP behavior while adding the intended metadata protections.

Regression protects:

1. Existing Erase / Program / Verify / DFU flow.
2. Existing Run flow, now with metadata-aware preconditions.
3. Existing Simulator mode.
4. Existing source-run GUI launch.
5. Existing Windows packaging flow.
6. Existing protocol frame format.
7. Existing SCI / RS232 communication assumptions.
8. Existing App conversion flow through hex2000.

## 2. Regression Scope

In scope:

1. PC unit tests.
2. PC simulator workflow tests.
3. DSP host tests.
4. CLI-style DFU / Run flows.
5. GUI source-run flow.
6. Packaged GUI launch.
7. Hardware RAM bootloader smoke flow.
8. Documentation consistency.

Out of scope:

1. APP_CONFIRMED implementation.
2. Automatic boot decision on reset.
3. Rollback.
4. CPU2 upgrade.
5. W5300/TCP upgrade.
6. A/B dual App.
7. Flash-resident bootloader conversion.

## 3. Address Migration Regression

Old App start:

```text
0x082000
```

New App start:

```text
0x082400
```

Required checks:

1. Test App linker files must use entry point at or after `0x082400`.
2. Generated `.out -> hex2000 -boot -a -sci8` image must not contain blocks in `0x082000 ~ 0x0823FF`.
3. PC FirmwareImage validation must reject old App images linked at `0x082000`.
4. PC FirmwareImage validation must accept App images linked at `0x082400`.
5. Program / Verify packets must never write metadata range.
6. Run entry point must be 8-word aligned and match metadata summary.

## 4. Automated Regression Checklist

Recommended source-run regression:

```powershell
python -m pytest
```

Focused simulator checks:

```powershell
python -m pytest tests/unit/test_simulator_workflow.py
```

DSP host checks:

```powershell
python -m pytest tests/unit/test_dsp_host.py
```

Pass criteria:

1. All existing unit tests pass.
2. Simulator workflow tests pass.
3. DSP host tests compile and pass when GCC is available.
4. No test requires the real Flash API.
5. No test requires connected hardware unless explicitly marked hardware/manual.

## 5. Simulator Regression Checklist

Simulator scenarios that must pass:

1. Connect / PING / GET_DEVICE_INFO.
2. Erase selected App sector.
3. Program App at `0x082400`.
4. Verify App at `0x082400`.
5. DFU appends IMAGE_VALID.
6. Failed Verify does not append IMAGE_VALID.
7. GET_METADATA_SUMMARY reports blank metadata correctly.
8. GET_METADATA_SUMMARY reports IMAGE_VALID correctly.
9. FLASH_READ metadata bounds are enforced.
10. `workflow.run()` appends BOOT_ATTEMPT before RUN.
11. Direct RUN without BOOT_ATTEMPT is rejected.
12. Run without metadata is rejected.
13. Run entry mismatch is rejected.
14. Attempt limit is enforced.
15. APP_CONFIRMED remains unsupported.

## 6. DSP Host Regression Checklist

DSP host regression requirements:

1. Protocol CRC16 behavior remains unchanged.
2. Byte-level magic resync remains unchanged.
3. Core forwards flash-service commands correctly.
4. Core rejects oversized service response payload.
5. Metadata parser validates record CRC32.
6. Metadata scanner handles blank, valid, corrupt, duplicate sequence, bad slot, bad entry.
7. IMAGE_VALID record builder uses 64-word layout.
8. BOOT_ATTEMPT record builder uses 64-word layout.
9. RUN rejects missing metadata.
10. RUN accepts metadata with BOOT_ATTEMPT.
11. Flash service rejects IMAGE_VALID append before Verify.
12. Flash service clears `verify_succeeded` after successful IMAGE_VALID append.
13. Flash service rejects BOOT_ATTEMPT before IMAGE_VALID.
14. Flash service enforces attempt limit.

Do not require the hardware Flash API in host tests.

## 7. GUI Source-Run Regression Checklist

Steps:

1. Start GUI using `python -m bootloader_upgrade_tool`.
2. Confirm GUI launches without import/runtime errors.
3. Select valid App `.out`.
4. Confirm hex2000 conversion succeeds.
5. Confirm firmware summary shows App range beginning at `0x082400`.
6. Confirm calculated sector mask does not include Sector A.
7. Connect to simulator.
8. Run DFU.
9. Run App.
10. Confirm simulator reports RUN_APP pending action or equivalent.

Expected result: GUI source-run workflow remains usable after metadata-gated Run
changes.

## 8. Hardware Regression Checklist

Hardware regression assumes:

1. User manually loads/runs RAM bootloader.
2. SCI/RS232 connection is used.
3. CPU1 / F28377D target.
4. App linked at `0x082400`.
5. Metadata area `0x082000 ~ 0x0823FF`.

Required hardware checks before Phase 10.2 close:

1. HW-RG-01 Connect + DeviceInfo.
2. HW-RG-02 Read blank metadata after Flash B erase.
3. HW-RG-03 DFU writes IMAGE_VALID.
4. HW-RG-04 Run writes BOOT_ATTEMPT.

Expected:

1. Device connects.
2. Metadata raw read returns expected words.
3. IMAGE_VALID appears after DFU.
4. BOOT_ATTEMPT appears after Run.

Optional hardware checks:

1. Direct RUN without BOOT_ATTEMPT rejected.
2. Attempt limit reached.
3. Failed Verify does not append IMAGE_VALID.

If raw command injection is unavailable, document these as simulator-required
and hardware-optional.

## 9. Packaging Regression Checklist

Required checks:

1. PyInstaller one-folder package builds.
2. Packaged GUI launches.
3. Packaged GUI can enter Simulator mode.
4. Packaged GUI can load/convert firmware if hex2000 path is available.
5. Packaged GUI does not bundle hex2000.
6. Documentation still explains `C200_CG_ROOT` and manual hex2000 path fallback.

Recommended packaging command:

```powershell
.\tools\package_windows.ps1
```

Do not change packaging behavior in Phase 10.2K.

## 10. Protocol Regression Checklist

Protocol invariants that must not change:

1. Frame layout unchanged.
2. CRC16 header/payload rules unchanged.
3. 16-bit word stream remains little-endian.
4. SCI autobaud `A` remains connection-layer behavior.
5. DSP remains slave; PC remains master.
6. No asynchronous DSP messages.
7. No ACK/NAK word protocol.
8. BAD_MAGIC / BAD_HEADER_CRC remain local diagnostics, not guaranteed DSP response statuses.
9. ProgramData / VerifyData remain 8-word aligned.
10. RamLoadData remains not 8-word constrained.

## 11. Metadata Regression Checklist

Metadata invariants:

1. Metadata start remains `0x082000`.
2. Metadata size remains 1024 words.
3. Metadata record size remains 64 words.
4. Metadata record count remains 16.
5. App start remains `0x082400`.
6. App end remains `0x0C0000`.
7. IMAGE_VALID is written only after successful Verify.
8. BOOT_ATTEMPT is written only before unconfirmed Run.
9. APP_CONFIRMED is not implemented.
10. Metadata append uses append-only journal.
11. Reserved words remain `0xFFFF`.
12. `record_crc32` covers words `0..61`.
13. `image_crc32` covers actual padded programmed words.

## 12. Documentation Regression Checklist

Required documentation consistency:

1. README documentation index includes docs/30 and docs/31.
2. docs/14 lists metadata commands and future APP_CONFIRM as reserved-only.
3. docs/27 metadata header design remains consistent with current constants.
4. docs/28 implementation plan references docs/30 and docs/31.
5. docs/30 test plan remains consistent with 10.2K regression requirements.
6. No document claims APP_CONFIRMED is implemented.
7. No document claims automatic boot decision is implemented.
8. No document claims rollback is implemented.

## 13. Phase 10.2 Exit Criteria

Phase 10.2 can be considered complete only when:

1. All automated tests pass.
2. DSP host tests pass where GCC is available.
3. Simulator DFU + Run + metadata summary path passes.
4. Source-run GUI launches and simulator flow works.
5. Hardware HW-RG-01 through HW-RG-04 pass at least once.
6. Program/Verify cannot write metadata range.
7. IMAGE_VALID is written only after successful Verify.
8. BOOT_ATTEMPT is written before unconfirmed Run.
9. Attempt limit is enforced.
10. Known gaps are documented.

Phase 10.2 must not be marked complete if:

1. Normal ProgramData can write metadata.
2. IMAGE_VALID can be written without Verify.
3. Run can bypass BOOT_ATTEMPT for unconfirmed App.
4. Attempt limit can be bypassed.
5. APP_CONFIRMED is accidentally exposed.
6. GUI cannot launch.
7. Simulator flow is broken.
8. Hardware connect/device info fails.
