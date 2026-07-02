# 28 Phase 10.2 Implementation Plan

## 1. Purpose

This document plans Phase 10.2 implementation for App metadata and reliability
features after v0.1.0.

The goal is to split the work into small, reviewable, low-risk sub-phases. The
plan avoids implementing all metadata features at once and preserves current
v0.1.0 behavior until each new capability is individually implemented, tested,
and enabled.

## 2. Scope

This phase is documentation and planning only.

Do not modify or implement in this document:

- DSP source code.
- PC source code.
- protocol implementation.
- GUI implementation.
- Flash service implementation.
- existing test scripts.

Phase 10.2 implementation will build on:

```text
docs/26_protocol_extension_for_reliability.md
docs/27_app_slot_metadata_header_design.md
```

The project continues using the RAM bootloader during development and testing.
Flash-resident bootloader behavior remains a long-term target.

## 3. Implementation Principles

Phase 10.2 must follow these principles:

```text
1. Implement in small steps.
2. Keep v0.1.0 CLI and GUI flows working after every step.
3. Do not change existing protocol frame format.
4. Do not change existing command semantics.
5. Do not implement CPU2, W5300, A/B dual App, signing, encryption, or Flash-resident bootloader in Phase 10.2.
6. Do not move low-level hardware logic into Codex-generated code.
7. Keep hardware-specific work in user-port files.
8. Keep Flash API details behind existing user Flash abstraction.
9. Keep metadata parsing separate from raw protocol framing.
10. Keep App Program range separate from metadata write range.
11. Add tests before or with each implementation step.
```

The safest rollout is feature-gated. New metadata commands and metadata-gated
Run behavior should remain disabled until their required earlier steps are
verified.

Frozen metadata layout from `docs/27_app_slot_metadata_header_design.md`:

```text
slot_a_metadata_start = 0x082000
slot_a_metadata_words = 1024
slot_a_app_start      = 0x082400
slot_a_app_end        = 0x0C0000

record_words          = 64
record_bytes          = 128
record_count          = 16

boot_attempt_limit    = 3
```

Metadata area:

```text
0x082000 ~ 0x0823FF
```

App image area:

```text
0x082400 ~ 0x0BFFFF
```

Current record types:

```c
#define BOOT_METADATA_RECORD_IMAGE_VALID    0x0001
#define BOOT_METADATA_RECORD_BOOT_ATTEMPT   0x0002
#define BOOT_METADATA_RECORD_APP_CONFIRMED  0x0003
```

Frozen record model:

```text
64 words per record
16 records total
record_crc32 = CRC32(words 0..61)
words 62..63 store record_crc32
reserved words = 0xFFFF
```

## 4. Phase 10.2 Sub-phase Overview

| Sub-phase | Goal | Code enabled by default? |
|---|---|---|
| 10.2A | Define shared App/metadata address boundaries | Yes, as constants only |
| 10.2B | Reject FirmwareImage/App Program overlap with metadata | Yes, when App start migration begins |
| 10.2C | Add PC/DSP CRC32 utility and tests | Yes, utility only |
| 10.2D | Parse and scan metadata records on DSP | No boot decision yet |
| 10.2E | Implement safe `FLASH_READ` metadata raw read | Feature-gated |
| 10.2F | Implement `GET_METADATA_SUMMARY` | Feature-gated |
| 10.2G | Append `IMAGE_VALID` after Verify | Feature-gated |
| 10.2H | Append `BOOT_ATTEMPT` before Run | Feature-gated |
| 10.2I | Prepare `APP_CONFIRMED` API boundary | Design stub only |
| 10.2J | Add tests for each sub-phase | With each sub-phase |
| 10.2K | Run regression gates | After each behavior change |

Recommended implementation order:

```text
10.2A -> 10.2B -> 10.2C -> 10.2D -> 10.2E -> 10.2F -> 10.2G -> 10.2H -> 10.2I
```

## 5. Phase 10.2A Address Boundary Constants

Goal:

```text
Define shared App/metadata address boundary constants.
```

Required concepts:

```text
SLOT_A_METADATA_START = 0x082000
SLOT_A_METADATA_WORDS = 1024
SLOT_A_METADATA_END   = 0x082400
SLOT_A_APP_START      = 0x082400
SLOT_A_APP_END        = 0x0C0000
```

DSP side should eventually have these constants in a user-address-limit or
metadata layout header. PC side should eventually have matching constants in
Flash sector / layout helpers.

Avoid duplicated unsynchronized magic numbers. A future single-source layout
file is preferred, but Phase 10.2 may manually define constants on both sides
if that is the shortest reviewable step. If manual constants are used, tests
must compare PC and DSP-visible values through generated vectors or shared
documentation checks.

Acceptance:

```text
1. Constants are defined consistently on PC and DSP sides.
2. Existing Sector A protection remains unchanged.
3. Existing Flash B sector handling remains valid.
4. Program / Verify App ranges can distinguish metadata area from App area.
```

## 6. Phase 10.2B PC FirmwareImage and GUI Metadata Range Protection

Goal:

```text
Prevent .out / FirmwareImage from writing into metadata area.
```

Required behavior:

```text
1. FirmwareImage validation rejects any block overlapping 0x082000 ~ 0x0823FF.
2. App blocks are allowed only in 0x082400 ~ 0x0BFFFF.
3. GUI must display new App start = 0x082400.
4. GUI sector mask calculation still includes Flash B if App uses Flash B remainder.
5. Program operation must never send ProgramData for metadata words.
6. Verify operation must never VerifyData metadata words as App payload.
```

Acceptance:

```text
1. Old App linked at 0x082000 is rejected with a clear error.
2. New App linked at 0x082400 is accepted.
3. Sector mask includes Flash B when App uses 0x082400+.
4. Sector A remains protected.
5. Existing Phase 6/7 tests are updated or duplicated to use the new App start only when this implementation step begins.
```

Do not update tests in this planning document. Future implementation should add
or update tests in the same change that enables the new App start.

## 7. Phase 10.2C CRC32 Utility

Goal:

```text
Add shared CRC32 implementation for PC and DSP.
```

CRC32 definition:

```text
CRC32/IEEE
poly   = 0xEDB88320
init   = 0xFFFFFFFF
xorout = 0xFFFFFFFF
input order: each 16-bit word low byte first, then high byte
```

Use cases:

```text
image_crc32
metadata record CRC
RAM_CHECK_CRC
future diagnostics
```

Implementation planning notes:

```text
1. PC implementation can be straightforward Python.
2. DSP implementation should initially use a simple bitwise implementation.
3. No large lookup table is required initially.
4. Add a test vector document or unit tests to verify PC/DSP consistency.
```

Phase 10.2C implementation status:

```text
1. PC CRC32 utility added.
2. DSP bitwise CRC32 utility added.
3. Shared test vectors added in unit tests.
4. No metadata integration yet.
5. No image_crc32 workflow integration yet.
6. No RAM_CHECK_CRC integration yet.
```

CRC32 over empty input is:

```text
0x00000000
```

Reason:

```text
init 0xFFFFFFFF xorout 0xFFFFFFFF with no input bytes.
```

Acceptance:

```text
1. PC and DSP CRC32 produce the same value for the same word array.
2. CRC32 over empty input is defined.
3. CRC32 over 0xFFFF padded data is tested.
4. Low-byte-first word order is tested.
```

## 8. Phase 10.2D DSP Metadata Record Parser and Scanner

Goal:

```text
Implement metadata record parsing and scanning without writing metadata yet.
```

Required scanner behavior:

```text
1. Scan 16 records.
2. Skip all-0xFFFF records.
3. Validate magic0/magic1.
4. Validate record_version.
5. Validate record_words == 64.
6. Validate record_type.
7. Validate slot_id == BOOT_SLOT_A.
8. Validate App range.
9. Validate entry point range and alignment.
10. Validate record_crc32.
11. Ignore corrupted records.
12. Choose newest valid record by largest sequence number.
13. If duplicate sequence numbers are found among valid records, treat automatic boot decision as invalid and stay bootloader.
```

Current implementation should only parse and summarize. Do not yet perform
automatic boot decision in the RAM bootloader.

Acceptance:

```text
1. Blank metadata area reports metadata invalid.
2. One valid IMAGE_VALID record is parsed correctly.
3. Corrupted latest record is ignored.
4. Previous valid record can still be used.
5. Invalid slot_id is rejected.
6. Invalid entry point is rejected.
7. Duplicate sequence behavior is defined.
```

## 9. Phase 10.2E FLASH_READ Metadata Raw Read

Goal:

```text
Implement only safe metadata raw read first.
```

Command from `docs/26_protocol_extension_for_reliability.md`:

```c
#define BOOT_CMD_FLASH_READ 0x0230
```

Initial implementation scope:

```text
read_target = BOOT_READ_TARGET_METADATA only
```

Do not initially implement:

```text
BOOT_READ_TARGET_APP
BOOT_READ_TARGET_RAW_FLASH
```

Required behavior:

```text
1. Allow reading only 0x082000 ~ 0x0823FF.
2. Enforce max_read_words.
3. Reject out-of-range address.
4. Return raw Flash words.
5. No write side effects.
```

Acceptance:

```text
1. GUI/CLI can read blank metadata area.
2. Reading outside metadata area returns ADDRESS_OUT_OF_RANGE.
3. Reading Sector A is rejected.
4. Reading App area is not implemented initially unless explicitly enabled later.
```

## 10. Phase 10.2F GET_METADATA_SUMMARY

Goal:

```text
Implement DSP-parsed metadata summary.
```

Command from `docs/26_protocol_extension_for_reliability.md`:

```c
#define BOOT_CMD_GET_METADATA_SUMMARY 0x0401
```

Response should include at least:

```text
metadata_valid
active_slot
latest_record_type
boot_attempt_count
app_confirmed
app_version_major
app_version_minor
app_version_patch
app_version_build
entry_point
image_crc32
flags
```

Required behavior:

```text
1. Use DSP metadata scanner.
2. Do not rely on PC parsing raw metadata.
3. Blank metadata returns metadata_valid = 0.
4. Corrupted records are ignored.
5. Summary reflects latest valid IMAGE_VALID / BOOT_ATTEMPT / APP_CONFIRMED relationship.
```

Acceptance:

```text
1. Blank metadata summary works.
2. Valid IMAGE_VALID summary works.
3. BOOT_ATTEMPT count works.
4. APP_CONFIRMED state works.
5. Corrupted record fallback works.
```

Phase 10.2F implementation status:

1. GET_METADATA_SUMMARY command has been added.
2. DSP returns parsed BootMetadataSummary.
3. Response payload is exactly 25 words.
4. Metadata is read through direct Flash address access wrapper.
5. PC client decodes the response into MetadataSummary.
6. Simulator supports blank metadata summary.
7. No metadata write path has been added.
8. No Run boot decision integration has been added.
9. No GUI metadata page has been added.

## 11. Phase 10.2G IMAGE_VALID Append after Verify

Goal:

```text
Plan the first metadata write operation.
```

Required behavior:

```text
1. After App Program + Verify succeeds, bootloader appends IMAGE_VALID record.
2. IMAGE_VALID includes image_crc32 from PC.
3. IMAGE_VALID includes app version fields.
4. IMAGE_VALID includes entry point.
5. IMAGE_VALID includes app_start/app_end/image_size_words.
6. IMAGE_VALID record is written only after Verify succeeds.
```

Design options:

| Option | Description | Tradeoff |
|---|---|---|
| A | Append inside `VerifyEnd` automatically | Fewer host steps, but hides a Flash metadata write inside Verify. |
| B | Add a separate metadata-specific command after `VerifyEnd` | Explicit, but expands public protocol sooner. |
| C | Add a separate metadata-specific internal workflow step after `VerifyEnd` succeeds | Visible in logs while keeping Verify pure and protocol surface smaller initially. |

Recommendation:

```text
Use Option C first: a separate metadata-specific internal workflow step after VerifyEnd succeeds.
Do not hide metadata write inside VerifyEnd until the design is tested.
```

Reason:

```text
1. Keeps Verify as pure data check.
2. Makes metadata write visible in GUI logs.
3. Easier to debug.
4. Easier to retry or diagnose.
5. Avoids committing to a public arbitrary metadata append command too early.
```

Acceptance:

```text
1. Metadata is not written before Verify succeeds.
2. Failed Verify does not write IMAGE_VALID.
3. IMAGE_VALID write failure makes App untrusted.
4. GUI logs metadata write result clearly.
```

Phase 10.2G implementation status:

1. IMAGE_VALID append is implemented after successful DFU verify.
2. Metadata append is a separate workflow step after Verify succeeds.
3. VerifyEnd semantics remain unchanged.
4. IMAGE_VALID includes image_crc32 from PC.
5. IMAGE_VALID includes App version fields.
6. IMAGE_VALID is written to append-only metadata journal.
7. Metadata write failure makes DFU fail.
8. BOOT_ATTEMPT append is implemented in Phase 10.2H.
9. No APP_CONFIRMED append has been added yet.
10. Run behavior is metadata-gated in Phase 10.2H.

## 12. Phase 10.2H BOOT_ATTEMPT Append before Run

Goal:

```text
Append BOOT_ATTEMPT before running unconfirmed App.
```

Required behavior:

```text
1. Run scans metadata.
2. If no IMAGE_VALID exists, reject Run.
3. If entry point does not match metadata/range, reject Run.
4. If APP_CONFIRMED exists, Run without appending BOOT_ATTEMPT.
5. If IMAGE_VALID exists but APP_CONFIRMED does not:
   - check boot_attempt_count;
   - if count < boot_attempt_limit, append BOOT_ATTEMPT;
   - then Run;
   - if count >= limit, reject Run and stay bootloader.
```

Acceptance:

```text
1. Run without metadata is rejected.
2. Run with IMAGE_VALID appends BOOT_ATTEMPT.
3. Run after 3 failed attempts is rejected.
4. Run with APP_CONFIRMED does not append BOOT_ATTEMPT.
5. Existing v0.1.0 Run behavior is not broken until metadata feature is enabled.
```

Important staging rule:

```text
Metadata-gated Run must be feature-gated or build-gated until IMAGE_VALID append
and GET_METADATA_SUMMARY are working, otherwise current hardware Run tests will
fail before replacement tests exist.
```

Phase 10.2H implementation status:

1. BOOT_ATTEMPT append is implemented before Run for unconfirmed App.
2. BOOT_ATTEMPT append uses METADATA_APPEND_RECORD.
3. BOOT_ATTEMPT does not require verify_succeeded.
4. Run now requires valid IMAGE_VALID metadata.
5. Run rejects entry point mismatch.
6. Run rejects unconfirmed App after boot_attempt_limit is reached.
7. APP_CONFIRMED write is not implemented yet.
8. Automatic boot decision is not implemented yet.
9. Run behavior is metadata-aware but no rollback is implemented yet.

Phase 10.2H-1 test cleanup status:

1. BOOT_ATTEMPT append before IMAGE_VALID is covered.
2. Run without metadata is covered.
3. Run entry mismatch is covered.
4. Attempt limit reached is covered.
5. Direct RUN without BOOT_ATTEMPT is covered.
6. Metadata command documentation has been updated.

## 13. Phase 10.2I Optional APP_CONFIRMED Design Stub

Goal:

```text
Do not fully implement App Confirm yet, but prepare the API boundary.
```

Preferred future production flow:

```text
1. PC performs DFU.
2. After Program + Verify succeeds, bootloader appends IMAGE_VALID.
3. PC requests Run.
4. Before Run, bootloader workflow appends BOOT_ATTEMPT.
5. Bootloader jumps to App.
6. App starts and performs its own initialization checks.
7. After stable startup, App calls App Confirm function.
8. App Confirm function appends APP_CONFIRMED record.
9. Future boot decisions treat this App as confirmed.
```

APP_CONFIRMED should be initiated by the App, not automatically by the
bootloader immediately after Run. Only the App can know whether its own
initialization, peripherals, control loop, communication, and safety checks have
completed successfully.

Planning decisions:

```text
1. APP_CONFIRMED is written by the running App after it has started successfully.
2. APP_CONFIRMED proves that the App passed its own initialization checks.
3. APP_CONFIRMED is appended to the same Slot A metadata journal.
4. APP_CONFIRMED does not erase or rewrite existing metadata.
5. APP_CONFIRMED is not implemented in Phase 10.2I.
```

Future App-callable API boundary:

```c
typedef enum
{
    BOOT_APP_CONFIRM_OK = 0,
    BOOT_APP_CONFIRM_INVALID_STATE,
    BOOT_APP_CONFIRM_METADATA_INVALID,
    BOOT_APP_CONFIRM_IMAGE_MISMATCH,
    BOOT_APP_CONFIRM_METADATA_FULL,
    BOOT_APP_CONFIRM_WRITE_FAILED
} BootAppConfirmResult;

BootAppConfirmResult BootAppConfirm_Confirm(uint16_t slot_id,
                                            uint32_t image_crc32,
                                            uint32_t flags);
```

Future App-callable API rules:

```text
1. slot_id must be BOOT_SLOT_A for the current single-slot phase.
2. image_crc32 must match current IMAGE_VALID metadata.
3. flags must be 0 for now.
4. The function must run from RAM or from a RAM-resident service context.
5. The function must use the same Flash abstraction / metadata append path as IMAGE_VALID and BOOT_ATTEMPT.
6. The function must not call protocol frame code.
7. The function must not depend on PC connection state.
```

Future debug-host confirm boundary:

```text
BOOT_CMD_APP_CONFIRM = 0x0403 is reserved for future debug/App-confirm support.
It is not implemented in Phase 10.2I.
```

Future debug-host confirm constraints:

```text
1. Must be debug-only.
2. Must be hidden in normal GUI mode.
3. Must require metadata feature support.
4. Must require explicit debug/engineering mode.
5. Must validate slot_id and image_crc32.
6. Must never be used as the normal production confirmation path.
```

Future APP_CONFIRMED record construction:

```text
1. Initialize all 64 words to 0xFFFF.
2. record_type = BOOT_METADATA_RECORD_APP_CONFIRMED.
3. sequence = latest_sequence + 1.
4. slot_id = BOOT_SLOT_A.
5. slot_role = BOOT_SLOT_A.
6. flags = 0.
7. app_start = summary.app_start.
8. app_end = summary.app_end.
9. entry_point = summary.entry_point.
10. image_size_words = summary.image_size_words.
11. image_crc32 = summary.image_crc32.
12. app_version fields copied from summary.
13. target_device_id copied from summary.
14. target_cpu_id copied from summary.
15. boot_attempt_limit copied from summary.
16. boot_attempt_count copied from summary.
17. record_crc32 = CRC32(words 0..61).
18. Store record_crc32 low word at word 62 and high word at word 63.
```

Reserved words must remain `0xFFFF`.

Future validation before writing APP_CONFIRMED:

```text
1. Metadata scan must be valid.
2. IMAGE_VALID must exist.
3. Slot must be BOOT_SLOT_A.
4. image_crc32 must match current metadata summary.
5. target_device_id must match the current device.
6. target_cpu_id must match the current CPU.
7. APP_CONFIRMED should not be appended if the App is already confirmed.
8. Metadata journal must have a free record slot.
9. Duplicate sequence state must be rejected.
10. Metadata write must be verified by re-scanning the journal.
```

If already confirmed, return OK/no-op so repeated App Confirm calls do not
consume journal records.

Future boot decision impact:

```text
1. If APP_CONFIRMED exists, bootloader can trust and run the App without appending a new BOOT_ATTEMPT.
2. If IMAGE_VALID exists but APP_CONFIRMED does not exist, bootloader uses BOOT_ATTEMPT limit.
3. If boot_attempt_count reaches boot_attempt_limit without APP_CONFIRMED, bootloader stays in bootloader mode.
4. If metadata is invalid, bootloader stays in bootloader mode.
```

Phase 10.2I implementation status:

1. APP_CONFIRMED future production flow is documented.
2. App-callable confirm API boundary is documented.
3. Debug-host confirm command boundary is documented as future/debug-only.
4. APP_CONFIRMED record construction rules are documented.
5. APP_CONFIRMED validation rules are documented.
6. Future boot decision impact is documented.
7. No APP_CONFIRMED write path has been implemented.
8. No APP_CONFIRM command handler has been implemented.
9. No GUI confirm action has been implemented.
10. Automatic boot decision is not implemented.
11. Rollback is not implemented.

## 14. Phase 10.2J Test Plan

Complete test strategy is documented in `docs/30_phase_10_2_test_plan.md`.

Required test categories:

```text
1. PC unit tests for metadata range rejection.
2. PC CRC32 test vectors.
3. DSP metadata parser tests, if feasible.
4. Simulator tests for metadata summary.
5. Hardware tests for FLASH_READ metadata.
6. Hardware tests for metadata write after Verify.
7. Hardware tests for Run attempt count.
8. Regression tests for existing Erase / Program / Verify / Run.
```

Sub-phase test mapping:

| Sub-phase | Minimum tests |
|---|---|
| 10.2A | PC/DSP constant consistency check or generated vector check |
| 10.2B | Reject block overlapping `0x082000 ~ 0x0823FF`; accept block at `0x082400` |
| 10.2C | Empty CRC, low-byte-first word order, `0xFFFF` padded data |

Phase 10.2B implementation note: PC FirmwareImage validation rejects App
entry points and blocks outside `0x082400 ~ 0x0BFFFF`, including any overlap
with `0x082000 ~ 0x0823FF`. Flash B remains erasable; Program / Verify
payloads must not write metadata.

Phase 10.2D implementation status:

1. DSP metadata record parser added.
2. DSP metadata journal scanner added.
3. Scanner validates CRC32 and App range.
4. Scanner summarizes IMAGE_VALID / BOOT_ATTEMPT / APP_CONFIRMED.
5. No metadata write path yet.
6. No GET_METADATA_SUMMARY protocol command yet.
7. No Run boot decision integration yet.

| 10.2D | Blank, valid, corrupt latest, bad slot, bad entry, duplicate sequence |

Phase 10.2E implementation status:

1. FLASH_READ command added.
2. Metadata raw read target implemented.
3. Reads are limited to `0x082000 ~ 0x0823FF`.
4. Blank metadata reads return `0xFFFF`.
5. App read and raw Flash read remain unsupported.
6. No GET_METADATA_SUMMARY command yet.
7. No metadata write path yet.

| 10.2E | Read blank metadata, reject Sector A, reject App/raw targets |
| 10.2F | Blank summary, valid summary, attempts, confirmed, corrupt fallback |
| 10.2G | Verify success writes `IMAGE_VALID`; Verify failure does not |
| 10.2H | No metadata rejects Run only after gate enabled; attempt count limit |
| 10.2I | Interface/design review only |

Current v0.1.0 hardware tests should not be broken without replacement tests.
When App start changes from `0x082000` to `0x082400`, test App linker files and
expected entry point must be updated in the implementation change.

Phase 10.2J implementation status:

1. Phase 10.2 test levels are defined.
2. PC unit test scope is documented.
3. Simulator workflow test scope is documented.
4. DSP host test scope is documented.
5. Hardware smoke test scope is documented.
6. Power-loss/reset equivalent test cases are documented.
7. Regression test scope is documented.
8. Pass/fail criteria are documented.
9. Known gaps after Phase 10.2 are documented.
10. No new production functionality has been implemented.

## 15. Phase 10.2K Regression Requirements

Complete regression requirements are documented in
`docs/31_phase_10_2_regression_requirements.md`.

Required regression checks:

```text
1. CLI Phase 6.3 must still pass after test App is relinked to 0x082400.
2. CLI Phase 7.1 must still pass after metadata workflow is enabled.
3. GUI DFU + Run must still pass.
4. Packaged GUI should still launch.
5. Simulator mode should still work.
6. Existing v0.1.0 release behavior must remain understandable and documented.
```

Before enabling metadata-gated Run, run the existing Phase 6/7 flow with the
new App start and a replacement expected entry point. After enabling
metadata-gated Run, run the same flow plus metadata summary / journal checks.

Phase 10.2K implementation status:

1. Regression objective is documented.
2. Address migration regression requirements are documented.
3. Automated regression checklist is documented.
4. Simulator regression checklist is documented.
5. DSP host regression checklist is documented.
6. GUI source-run regression checklist is documented.
7. Hardware regression checklist is documented.
8. Packaging regression checklist is documented.
9. Protocol and metadata regression invariants are documented.
10. Phase 10.2 exit criteria are documented.
11. No new production functionality has been implemented.

## 16. Phase 10.2L Regression Execution and Evidence

Regression evidence is recorded in
`docs/32_phase_10_2_regression_evidence.md`.

Phase 10.2L implementation status:

1. Regression evidence document has been created.
2. Automated regression result is recorded.
3. Simulator workflow regression result is recorded.
4. DSP host regression result is recorded.
5. GUI source-run regression result is recorded or marked not executed.
6. Packaging regression result is recorded or marked not executed.
7. Hardware HW-RG-01 through HW-RG-04 are recorded as PASS/FAIL/PENDING.
8. Phase 10.2 closure decision is recorded.
9. No new production functionality has been implemented.

## 17. Journal Full Policy Discussion

Current metadata journal capacity:

```text
metadata_words = 1024
record_words = 64
record_count = 16
```

The journal can fill during repeated Run / `BOOT_ATTEMPT` / `APP_CONFIRMED`
testing.

Options:

| Option | Behavior | Phase 10.2 decision |
|---|---|---|
| A | Reject further metadata writes and stay bootloader | Use for normal builds |
| B | Require full DFU to erase Flash B and reset metadata | Accept as normal recovery path |
| C | Provide debug-only `METADATA_CLEAR` | Allow only in controlled test builds |
| D | Implement journal compaction | Defer |

Recommended current policy:

```text
For Phase 10.2:
  If journal is full, reject metadata append with METADATA_FULL.
  Stay in bootloader if confirmation/attempt record cannot be safely appended.
  Use debug-only METADATA_CLEAR only in controlled test builds, not normal GUI.
  Full DFU naturally erases Flash B and resets metadata.
```

Do not implement compaction in Phase 10.2.

## 18. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| App linker still starts at `0x082000` | Reject FirmwareImage overlap with a clear error; update test App linker before enabling metadata range protection. |
| GUI accidentally programs metadata area | Add FirmwareImage validation plus Program/Verify block guards before transport send. |
| DSP Program/Verify accepts metadata range | Add DSP-side address checks in the Flash service path; PC checks are not enough. |
| CRC32 mismatch between PC and DSP | Add shared test vectors and run both implementations against the same word arrays. |
| Metadata write fails after App Verify | Treat App as untrusted; log `METADATA_WRITE_FAILED`; do not Run as confirmed. |
| Journal fills during testing | Return `METADATA_FULL`; use full DFU or debug-only clear in test builds. |
| Run behavior breaks before metadata workflow is complete | Keep metadata-gated Run feature-gated until `IMAGE_VALID` write path exists. |
| App Confirm is unavailable, causing boot attempt limit to be reached | Keep the limit behavior explicit; provide debug recovery path for test builds. |
| Flash B erase removes metadata by design | Document that full DFU resets metadata and no valid metadata means stay in bootloader. |
| Future A/B layout is over-specified too early | Keep Slot B fields in records but do not assign a fixed Slot B address. |

## 19. Deferred Items

Explicitly deferred:

```text
1. Actual implementation in this document
2. Flash-resident bootloader
3. Automatic boot decision integration until parser/write path is validated
4. A/B dual App
5. Slot B layout
6. CPU2 upgrade
7. W5300 / TCP
8. Firmware signing
9. Encryption
10. DCSM unlock
11. Automatic rollback
12. Journal compaction
13. Production App Confirm until RAM function design is validated
```

## 20. Open Questions

1. Should Phase 10.2 use manual PC/DSP constants first, or add a small
   single-source layout file before any behavior changes?
2. Should `IMAGE_VALID` append be exposed as a protocol command later, or stay
   as an internal workflow step?
3. Should metadata write support live in the Flash service lib or in a smaller
   metadata-specific RAM service?
4. What exact host-visible error should be shown when a legacy App starts at
   `0x082000`?
5. Should `image_crc32` be verified during every Run, or only during
   diagnostics / metadata summary refresh?
6. When should debug-only `METADATA_CLEAR` become available, and how should it
   be hidden from normal GUI users?
