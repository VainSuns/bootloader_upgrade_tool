# Phase 10.2 Test Plan

## 1. Test Objective

Verify that Phase 10.2 metadata-based reliability mechanisms work correctly in
PC tools, simulator, DSP host tests, and hardware validation.

The plan covers:

1. Metadata address protection.
2. CRC32 consistency.
3. Metadata parser/scanner correctness.
4. FLASH_READ metadata raw read.
5. GET_METADATA_SUMMARY.
6. IMAGE_VALID append after Verify.
7. BOOT_ATTEMPT append before Run.
8. Metadata-aware Run behavior.
9. Power-loss/reset equivalent workflow cases.
10. Regression of existing Erase / Program / Verify / Run.

## 2. Test Levels

| Level | Name | Purpose |
|---|---|---|
| L0 | Static / constant consistency | Verify PC/DSP command IDs, status codes, metadata layout constants, Slot A App range, and payload word counts match. |
| L1 | PC unit tests | Verify PC-side FirmwareImage validation, CRC32, MetadataSummary decoding, and client payload construction. |
| L2 | PC simulator workflow tests | Verify full workflow behavior without hardware, including metadata append and Run gates. |
| L3 | DSP host tests compiled with GCC | Verify DSP protocol/core/service/common logic without real Flash API. |
| L4 | Hardware smoke tests using RAM bootloader | Verify target communication and happy-path metadata behavior on F28377D CPU1. |
| L5 | Hardware fault-injection / recovery tests | Verify reset/power-loss equivalent behavior where practical. |

### L0 Static / Constant Consistency

Must verify:

1. DSP and PC command IDs match.
2. DSP and PC status codes match.
3. Metadata layout constants match.
4. Slot A App range constants match.
5. Protocol payload word counts match.

### L1 PC Unit Tests

Must verify:

1. FirmwareImage validation rejects metadata overlap.
2. FirmwareImage validation accepts App starting at `0x082400`.
3. Programmed image CRC32 includes `0xFFFF` padding.
4. CRC32 uses low-byte-first word order.
5. MetadataSummary decoding rejects wrong payload length.
6. Client builds correct METADATA_APPEND_RECORD payloads.

### L2 Simulator Workflow Tests

Must verify:

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

### L3 DSP Host Tests

Must verify:

1. boot_protocol CRC and frame behavior.
2. Byte-level magic resync.
3. Metadata record parser/scanner.
4. IMAGE_VALID record builder.
5. BOOT_ATTEMPT record builder.
6. Service command forwarding.
7. Service rejects metadata append before Verify.
8. Service clears `verify_succeeded` after IMAGE_VALID append.
9. RUN rejects invalid metadata.
10. RUN accepts metadata with BOOT_ATTEMPT.

Host tests do not require the real Flash API. They may use:

```text
BOOT_FLASH_READ_WORD(address)=Test_ReadFlashWord(address)
```

## 3. Hardware Test Scope

Hardware tests assume:

1. User manually loads/runs RAM bootloader.
2. PC GUI connects through SCI/RS232.
3. Device is CPU1 / F28377D.
4. App image is linked at `0x082400`.
5. Metadata area is `0x082000 ~ 0x0823FF`.

Hardware tests do not assume:

1. Flash-resident bootloader.
2. Automatic boot on reset.
3. APP_CONFIRMED.
4. CPU2.
5. W5300/TCP.
6. Rollback.

## 4. Hardware Smoke Tests

### HW-01 Connect and Device Info

Steps:

1. Load RAM bootloader.
2. Open PC GUI.
3. Connect SCI/RS232.
4. Confirm PING succeeds.
5. Confirm GET_DEVICE_INFO succeeds.
6. Confirm protocol version and `max_data_words` are valid.

Expected: device connects reliably and reports CPU1/F28377D information.

### HW-02 Metadata Raw Read Blank Area

Steps:

1. Erase Flash B.
2. Use FLASH_READ metadata at `0x082000`.
3. Read first 16 words.

Expected: all returned words are `0xFFFF`.

### HW-03 Full DFU Writes IMAGE_VALID

Steps:

1. Build or select App linked at `0x082400`.
2. Run DFU.
3. After Program + Verify, metadata append should occur.
4. Call GET_METADATA_SUMMARY.

Expected:

```text
metadata_valid = 1
latest_record_type = IMAGE_VALID
boot_attempt_count = 0
app_confirmed = 0
entry_point = App entry point
image_crc32 matches PC calculated CRC32
```

### HW-04 Run App Appends BOOT_ATTEMPT

Steps:

1. Continue from successful HW-03.
2. Click Run / execute `workflow.run()`.
3. Read GET_METADATA_SUMMARY again.

Expected:

```text
latest_record_type = BOOT_ATTEMPT
boot_attempt_count = 1
App starts or pending RUN action is issued as expected.
```

### HW-05 Direct RUN Without BOOT_ATTEMPT Is Rejected

If a GUI/debug tool can send raw RUN:

1. Perform DFU so IMAGE_VALID exists.
2. Do not call `workflow.run()`.
3. Send RUN command directly.

Expected: RUN is rejected with INVALID_STATE.

If raw command is unavailable, keep this simulator-only until a debug CLI exists.

### HW-06 Attempt Limit Reached

Steps:

1. Perform DFU.
2. Run App three times without APP_CONFIRMED.
3. Attempt fourth Run.

Expected: fourth Run is rejected with ATTEMPT_LIMIT_REACHED or a workflow-level
boot attempt limit error.

Because APP_CONFIRMED is not implemented, every Run of the unconfirmed App
consumes one BOOT_ATTEMPT.

### HW-07 Failed Verify Does Not Write IMAGE_VALID

Steps:

1. Use a controlled path to cause Verify mismatch, or corrupt programmed image before Verify if supported.
2. Run DFU.
3. Read GET_METADATA_SUMMARY.

Expected: metadata remains invalid if no previous IMAGE_VALID exists, and no new
IMAGE_VALID record is appended.

If fault injection is not practical on hardware, keep this simulator-required
and hardware-optional.

## 5. Power-Loss / Reset Equivalent Tests

### PL-01 Reset Before Metadata Write

Scenario: Program and Verify succeed, but metadata append is not completed.

Expected: without valid IMAGE_VALID metadata, bootloader must not trust the App.
Phase 10.2 does not implement automatic boot decision, so this is future
boot-decision input.

### PL-02 Reset After IMAGE_VALID Before BOOT_ATTEMPT

Scenario: IMAGE_VALID exists, but no BOOT_ATTEMPT exists.

Expected: direct RUN is rejected; `workflow.run()` appends BOOT_ATTEMPT before
RUN.

### PL-03 Reset After BOOT_ATTEMPT Without APP_CONFIRMED

Scenario: BOOT_ATTEMPT exists, but App never confirms.

Expected: further Run attempts are allowed until `boot_attempt_limit` is
reached. After the limit, bootloader should reject Run / future auto boot.

## 6. Regression Tests

Existing behavior that must not regress:

1. PC simulator DFU still performs Erase / Program / Verify.
2. ProgramData still rejects metadata address range.
3. VerifyData still rejects metadata address range.
4. Flash writes remain 8-word aligned.
5. RAM load remains not 8-word constrained.
6. SCI protocol frame format is unchanged.
7. Run still validates target and entry alignment.
8. W5300/TCP remains unimplemented.
9. CPU2 remains unimplemented.
10. APP_CONFIRMED remains unimplemented.

## 7. Test Matrix

| Test ID | Level | Category | Purpose | Method | Expected Result | Required Before Release? | Automation Status |
|---|---|---|---|---|---|---|---|
| T10.2-A-001 | L0 | Constants | PC/DSP metadata constants match | Static/unit check | IDs and ranges match | Yes | Existing/required |
| T10.2-B-001 | L1 | Metadata range protection | Reject metadata overlap | PC unit test | Image rejected | Yes | Existing |
| T10.2-C-001 | L1 | CRC32 word order | Validate CRC32 vectors | PC/DSP unit tests | CRC matches vectors | Yes | Existing |
| T10.2-D-001 | L3 | Metadata parser/scanner | Validate records and scan summary | GCC host test | Scanner reports expected state | Yes | Existing |
| T10.2-E-001 | L2 | FLASH_READ metadata bounds | Enforce metadata read range | Simulator test | Bounds accepted/rejected | Yes | Existing |
| T10.2-F-001 | L2 | GET_METADATA_SUMMARY blank metadata | Decode blank metadata | Simulator test | Blank summary returned | Yes | Existing |
| T10.2-G-001 | L2 | DFU metadata | DFU appends IMAGE_VALID | Simulator workflow | IMAGE_VALID summary | Yes | Existing |
| T10.2-G-002 | L2 | Failed Verify | Verify failure does not append IMAGE_VALID | Simulator fault test | No IMAGE_VALID appended | Yes | Existing |
| T10.2-H-001 | L2 | Run attempt | Run appends BOOT_ATTEMPT | Simulator workflow | count increments | Yes | Existing |
| T10.2-H-002 | L2 | Run gate | Direct RUN without BOOT_ATTEMPT rejected | Simulator direct command | INVALID_STATE | Yes | Existing |
| T10.2-H-003 | L2 | Attempt limit | Fourth unconfirmed Run rejected | Simulator workflow | limit error | Yes | Existing |
| T10.2-HW-001 | L4 | Hardware connect | Connect/device info | GUI/hardware smoke | Device info valid | Yes | Manual |
| T10.2-HW-002 | L4 | Hardware FLASH_READ | Blank metadata read | GUI/debug/hardware | `0xFFFF` words | Yes | Manual |
| T10.2-HW-003 | L4 | Hardware DFU metadata | DFU writes IMAGE_VALID | GUI/hardware | IMAGE_VALID summary | Yes | Manual |
| T10.2-HW-004 | L4 | Hardware Run metadata | Run writes BOOT_ATTEMPT | GUI/hardware | BOOT_ATTEMPT summary | Yes | Manual |

## 8. Pass / Fail Criteria

Phase 10.2 passes when:

1. All existing PC unit tests pass.
2. All simulator workflow tests pass.
3. DSP host tests compile and pass when GCC is available.
4. Hardware HW-01 to HW-04 pass at least once on target board.
5. No Program/Verify packet can write metadata address range.
6. IMAGE_VALID is written only after successful Verify.
7. BOOT_ATTEMPT is written only before unconfirmed Run.
8. Run without valid metadata is rejected.
9. Attempt limit is enforced.
10. No APP_CONFIRMED write path exists yet.

Phase 10.2 fails if:

1. Metadata area can be written through normal ProgramData.
2. IMAGE_VALID can be appended without Verify success.
3. Run can start an unconfirmed App without BOOT_ATTEMPT.
4. Attempt limit can be bypassed.
5. APP_CONFIRMED is accidentally exposed or written.
6. Existing Erase / Program / Verify regresses.

## 9. Known Gaps After Phase 10.2

1. No automatic boot decision on reset.
2. No APP_CONFIRMED implementation.
3. No rollback.
4. No metadata clear command.
5. No journal compaction.
6. No hardware power-loss automated fixture.
7. No CPU2 upgrade path.
8. No W5300/TCP path.
9. No Flash-resident bootloader build.
10. No GUI metadata page unless implemented elsewhere.
