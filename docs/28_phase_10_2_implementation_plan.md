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
2. Reading outside metadata area returns READ_NOT_ALLOWED.
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

## 13. Phase 10.2I Optional APP_CONFIRMED Design Stub

Goal:

```text
Do not fully implement App Confirm yet, but prepare the API boundary.
```

Preferred future production flow:

```text
1. Bootloader provides App Confirm function in RAM with Flash service lib.
2. App starts and finishes its own initialization checks.
3. App calls the confirm function.
4. Confirm function validates slot_id and image_crc32.
5. Confirm function appends APP_CONFIRMED metadata record.
6. Future boot decisions treat this App as confirmed.
```

Planning decisions:

```text
1. APP_CONFIRM should eventually be both an App-callable RAM function and a debug host command.
2. GUI manual confirm must be debug-only, hidden unless the feature flag and debug mode both allow it.
3. Production confirm function should live with the RAM service lib or a small RAM metadata service.
4. Confirm function should use the same Flash abstraction / metadata append path as IMAGE_VALID and BOOT_ATTEMPT.
5. Confirm must validate slot_id, image_crc32, current metadata state, journal space, and App range before writing APP_CONFIRMED.
```

Current recommendation:

```text
Design only. Do not implement in Phase 10.2 unless earlier phases pass.
```

## 14. Phase 10.2J Test Plan

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
| 10.2D | Blank, valid, corrupt latest, bad slot, bad entry, duplicate sequence |
| 10.2E | Read blank metadata, reject Sector A, reject App/raw targets |
| 10.2F | Blank summary, valid summary, attempts, confirmed, corrupt fallback |
| 10.2G | Verify success writes `IMAGE_VALID`; Verify failure does not |
| 10.2H | No metadata rejects Run only after gate enabled; attempt count limit |
| 10.2I | Interface/design review only |

Current v0.1.0 hardware tests should not be broken without replacement tests.
When App start changes from `0x082000` to `0x082400`, test App linker files and
expected entry point must be updated in the implementation change.

## 15. Phase 10.2K Regression Requirements

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

## 16. Journal Full Policy Discussion

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

## 17. Risks and Mitigations

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

## 18. Deferred Items

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

## 19. Open Questions

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
