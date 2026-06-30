# 27 App Slot Metadata Header Design

## 1. Purpose

This document designs the App Slot Metadata Header mechanism for the next
industrial reliability phase.

The metadata mechanism is the basis for:

- preventing boot of incomplete or corrupted App images;
- supporting failed-upgrade recovery;
- supporting future Flash-resident bootloader boot decisions;
- supporting future App confirmation;
- supporting future A/B App selection;
- supporting future GUI metadata display.

Current stage implements only Slot A. Future A/B support is considered in the
record format, but App B implementation is deferred.

## 2. Scope

This phase is documentation and design only.

Do not modify or implement:

- DSP source code;
- PC source code;
- protocol implementation;
- GUI implementation;
- Flash service implementation;
- existing test scripts.

This document builds on `docs/26_protocol_extension_for_reliability.md`,
especially `FLASH_READ`, `GET_METADATA_SUMMARY`, `APP_CONFIRM`, `CRC32`, and
`image_crc32`.

## 3. Design Decisions

Frozen parameters:

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

The metadata area is an append-only fixed-size record journal.

There is no in-place metadata state update. There is no repeated Flash erase
for metadata state changes.

Current stage defines Slot A only:

```c
#define BOOT_SLOT_AUTO 0x0000
#define BOOT_SLOT_A    0x0001
#define BOOT_SLOT_B    0x0002
```

Current active slot:

```text
slot_id = BOOT_SLOT_A
```

Future Slot B is reserved but not fixed. Do not define a fixed Slot B metadata
address in this document because App A actual size is not finalized and
premature App B partitioning may waste Flash space.

## 4. Flash Layout

Current stage layout:

```text
Flash A:
  reserved for future Flash-resident bootloader

Flash B:
  Slot A metadata journal starts at 0x082000
  Slot A app image starts at 0x082400

Flash B remainder ~ Flash N:
  Slot A app image
```

Metadata area:

```text
0x082000 ~ 0x0823FF:
  Slot A metadata journal area
```

App image area:

```text
0x082400 ~ 0x0BFFFF:
  Slot A app image area
```

Rules:

```text
1. Normal App Program / Verify must not write metadata area.
2. Metadata writes must use a dedicated metadata write path.
3. App linker command file must place the App after metadata area.
4. App image must not contain records or data in metadata area.
5. Metadata start, metadata size, and App start must remain 8-word aligned.
6. Metadata and App must not share the same ECC programming unit.
7. If metadata is invalid, bootloader must not boot the App.
```

## 5. Slot A Layout

Slot A regions:

| Region | Start | End | Size | Purpose |
|---|---:|---:|---:|---|
| Slot A metadata journal | `0x082000` | `0x082400` exclusive | `1024` words | Append-only metadata records |
| Slot A App image | `0x082400` | `0x0C0000` exclusive | `0x3DC00` words | CPU1 Flash App |

The metadata journal holds:

```text
record_words = 64
record_count = 16
```

GUI must reject firmware images that write into:

```text
0x082000 ~ 0x0823FF
```

GUI and DSP must treat the valid App area as:

```text
0x082400 ~ 0x0BFFFF
```

GUI sector mask calculation must still include Flash B if the App uses the
Flash B remainder, but Program must not write metadata words.

## 6. Metadata Journal Model

Metadata uses:

```text
append-only fixed-size record journal
```

Each metadata record is written only once.

Bootloader scans the metadata journal and selects the newest valid record by:

```text
valid magic
valid record version
valid record type
valid CRC32
largest sequence number
```

If the latest physical record is partially written or corrupted, bootloader
ignores it and uses the previous valid record.

If no valid `IMAGE_VALID` record exists, bootloader stays in bootloader.

## 7. Record Types

Current stage defines:

```c
#define BOOT_METADATA_RECORD_IMAGE_VALID    0x0001
#define BOOT_METADATA_RECORD_BOOT_ATTEMPT   0x0002
#define BOOT_METADATA_RECORD_APP_CONFIRMED  0x0003
```

### IMAGE_VALID

Written by bootloader after:

```text
Program App
Verify App
```

Purpose:

```text
The App image is complete, verified, has a valid entry point, and can be
considered a boot candidate.
```

### BOOT_ATTEMPT

Written by bootloader before trying to boot an unconfirmed App.

Purpose:

```text
Track how many times the bootloader has tried to start an IMAGE_VALID but not
yet APP_CONFIRMED App.
```

### APP_CONFIRMED

Written after App has started successfully.

Current stage only designs this interface.

Preferred future implementation:

```text
A bootloader-provided App Confirm function is placed in RAM together with the
Flash service lib. The App calls this function after successful initialization.
The confirm function appends APP_CONFIRMED metadata record.
```

GUI manual confirmation may be used for debug, but production confirmation
should be done by the App.

## 8. 64-word Record Format

Metadata magic and version constants:

```c
#define BOOT_METADATA_MAGIC0         0x4D42
#define BOOT_METADATA_MAGIC1         0x4453
#define BOOT_METADATA_RECORD_VERSION 0x0001
#define BOOT_METADATA_RECORD_WORDS   64
```

Fixed record layout:

| Word | Field | Notes |
|---:|---|---|
| 0 | `magic0` | `BOOT_METADATA_MAGIC0` |
| 1 | `magic1` | `BOOT_METADATA_MAGIC1` |
| 2 | `record_version` | `BOOT_METADATA_RECORD_VERSION` |
| 3 | `record_words` | Must be `64` |
| 4 | `record_type` | `IMAGE_VALID`, `BOOT_ATTEMPT`, or `APP_CONFIRMED` |
| 5 | `sequence_low` | Low word of monotonic sequence |
| 6 | `sequence_high` | High word of monotonic sequence |
| 7 | `slot_id` | Current stage must be `BOOT_SLOT_A` |
| 8 | `slot_role` | Slot role for future A/B policy |
| 9 | `flags` | Record-level flags; zero unless defined |
| 10 | `app_start_low` | Low word of App start address |
| 11 | `app_start_high` | High word of App start address |
| 12 | `app_end_low` | Low word of App end address, exclusive |
| 13 | `app_end_high` | High word of App end address, exclusive |
| 14 | `entry_point_low` | Low word of App entry point |
| 15 | `entry_point_high` | High word of App entry point |
| 16 | `image_size_words_low` | Low word of programmed padded image words |
| 17 | `image_size_words_high` | High word of programmed padded image words |
| 18 | `image_crc32_low` | Low word of image CRC32 |
| 19 | `image_crc32_high` | High word of image CRC32 |
| 20 | `app_version_major` | App version major |
| 21 | `app_version_minor` | App version minor |
| 22 | `app_version_patch` | App version patch |
| 23 | `app_version_build_low` | Low word of App build number |
| 24 | `app_version_build_high` | High word of App build number |
| 25 | `target_device_id` | Expected device ID, for example F28377D |
| 26 | `target_cpu_id` | Expected CPU ID, current stage CPU1 |
| 27 | `boot_attempt_limit` | Current default is `3` |
| 28 | `boot_attempt_count` | Attempt count encoded by `BOOT_ATTEMPT`; otherwise summary value or `0` |
| 29..61 | `reserved` | Must be `0xFFFF` |
| 62 | `record_crc32_low` | Low word of record CRC32 |
| 63 | `record_crc32_high` | High word of record CRC32 |

The record is exactly 64 words.

CRC protection:

```text
record_crc32 = CRC32(words 0..61)
```

The CRC field itself, words 62 and 63, is excluded.

Reserved field convention:

```text
reserved words = 0xFFFF
```

Reason:

```text
Erased Flash reads as 0xFFFF. Keeping unused fields at 0xFFFF avoids
programming unnecessary zero bits, makes blank/unused areas obvious, and leaves
more one-way programming margin inside a record. Defined flags and counters use
0x0000 only where zero is semantically meaningful.
```

## 9. CRC32 and Validation Rules

Use the same CRC32 definition as
`docs/26_protocol_extension_for_reliability.md`:

```text
CRC32/IEEE
poly   = 0xEDB88320
init   = 0xFFFFFFFF
xorout = 0xFFFFFFFF
```

Input order:

```text
Each 16-bit word is processed low byte first, then high byte.
```

Use CRC32 for:

```text
metadata record CRC
image_crc32
future diagnostics
```

Do not replace existing protocol frame CRC16.

Metadata record validation:

```text
1. magic0 and magic1 match.
2. record_version is supported.
3. record_words is 64.
4. record_type is known.
5. slot_id is valid; current stage requires BOOT_SLOT_A.
6. app_start/app_end match the allowed slot range.
7. entry_point is inside Slot A App range.
8. entry_point alignment follows Flash App Run rules.
9. image_crc32 matches the programmed padded image words when checked.
10. record_crc32 matches CRC32(words 0..61).
```

Invalid records are ignored during scan.

## 10. image_crc32 Rule

`image_crc32` is calculated by the PC GUI.

It covers:

```text
all actual padded image words programmed to Flash
```

It includes:

```text
0xFFFF padding inserted by the PC to satisfy 8-word Flash programming alignment
```

It does not include:

```text
metadata area
unwritten gaps between firmware blocks
unused Flash area
```

Current-stage rule:

```text
CRC covers only FirmwareImage padded blocks in address order.
```

## 11. Metadata Scan Algorithm

Bootloader scans all 16 records in the Slot A metadata area.

Algorithm:

```text
valid_records = []

for each physical record in journal order:
  if record is all 0xFFFF:
    continue
  if magic/version/type/record_words are invalid:
    continue
  if CRC32(words 0..61) does not match words 62..63:
    continue
  if slot_id is not BOOT_SLOT_A:
    continue
  if App range or entry point is invalid:
    continue
  add record to valid_records

select newest valid record by largest sequence number
```

For current single-slot boot, the bootloader also finds the latest valid
`IMAGE_VALID`, counts valid `BOOT_ATTEMPT` records after it, and checks whether
an `APP_CONFIRMED` record exists after it.

Partially written or corrupted records are ignored.

If two records have the same valid sequence number, treat the journal as invalid
for automatic boot and stay in bootloader.

## 12. Boot Decision

Current single-App boot decision:

```text
If no valid IMAGE_VALID record exists:
  stay in bootloader

If IMAGE_VALID exists but APP_CONFIRMED does not exist:
  if boot_attempt_count < boot_attempt_limit:
      append BOOT_ATTEMPT
      jump Slot A App
  else:
      stay in bootloader

If APP_CONFIRMED exists:
  jump Slot A App
```

Invalid conditions:

```text
metadata CRC invalid
record type invalid
entry point outside Slot A App range
entry point not aligned as required
image CRC mismatch
slot_id invalid
boot_attempt_count >= boot_attempt_limit
```

In these cases:

```text
stay in bootloader
```

## 13. Boot Attempt Counting

`BOOT_ATTEMPT` records are counted after the latest valid `IMAGE_VALID` record.

Rules:

```text
1. Each attempt to boot an unconfirmed App appends one BOOT_ATTEMPT record.
2. boot_attempt_count is the number of valid BOOT_ATTEMPT records after the latest IMAGE_VALID.
3. APP_CONFIRMED clears the practical need for boot attempt limit.
4. Once APP_CONFIRMED exists after the latest IMAGE_VALID, bootloader may boot the App normally.
5. If boot_attempt_count reaches boot_attempt_limit before confirmation, stay in bootloader.
```

Default:

```text
boot_attempt_limit = 3
```

## 14. Upgrade Flow

Current stage upgrade flow:

```text
1. GUI selects App .out.
2. GUI converts .out -> hex2000 -> sci8 -> FirmwareImage.
3. GUI calculates image_crc32 over padded image words.
4. GUI connects to bootloader.
5. GUI performs Erase for App sectors including Flash B.
6. GUI / bootloader Program App, skipping metadata area.
7. GUI / bootloader Verify App.
8. After Verify succeeds, bootloader appends IMAGE_VALID record.
9. GUI may run App.
10. Before running unconfirmed App, bootloader appends BOOT_ATTEMPT.
11. App confirmation is designed but may be implemented later.
```

Metadata is written after App Verify succeeds.

There is no explicit `PENDING_UPDATE` record in the current stage.

Reason:

```text
Metadata and App share Flash B. When Flash B is erased at the beginning of
update, old metadata becomes invalid. No valid metadata means the App is not
trusted and bootloader stays in bootloader.
```

## 15. Run Flow

Current stage Run flow with metadata:

```text
1. Host requests Run.
2. Bootloader scans metadata.
3. Bootloader rejects Run if no valid IMAGE_VALID record exists.
4. Bootloader validates the requested entry point against the metadata and Slot A App range.
5. If App is unconfirmed, bootloader checks boot_attempt_count.
6. If boot attempts remain, bootloader appends BOOT_ATTEMPT.
7. Bootloader sends OK response.
8. Bootloader flushes SCI TX.
9. Bootloader jumps to Slot A App.
```

If App is already confirmed, the bootloader does not need to append a
`BOOT_ATTEMPT` record before Run.

## 16. App Confirm Flow

Current stage only designs App Confirm.

Preferred future production flow:

```text
1. Bootloader provides an App Confirm function in RAM with the Flash service lib.
2. App starts and finishes its own initialization checks.
3. App calls the bootloader-provided confirm function.
4. Confirm function validates slot_id and image_crc32.
5. Confirm function appends APP_CONFIRMED metadata record.
6. Future boot decisions treat this App as confirmed.
```

Debug-only GUI manual confirmation may be allowed later, but production
confirmation should come from the App.

## 17. Power-Loss Behavior

| Case | Expected behavior |
|---|---|
| Power loss before erase | Existing valid metadata, if any, remains usable. |
| Power loss during erase | Metadata or App may be invalid; if no valid metadata remains, stay in bootloader. |
| Power loss after erase before program | No valid metadata exists; stay in bootloader. |
| Power loss during program | No new `IMAGE_VALID` exists; stay in bootloader. |
| Power loss after program before verify | No new `IMAGE_VALID` exists; stay in bootloader. |
| Power loss after verify before `IMAGE_VALID` record | App may be programmed, but it is not trusted; stay in bootloader. |
| Power loss while writing `IMAGE_VALID` record | Corrupted record is ignored; use previous valid record or stay in bootloader. |
| Power loss after `IMAGE_VALID` before Run | App is a boot candidate; boot attempts are limited by `boot_attempt_limit`. |
| Power loss after `BOOT_ATTEMPT` before App confirms | Attempt remains counted; retry only until the limit is reached. |
| Power loss while writing `APP_CONFIRMED` record | Corrupted record is ignored; App remains unconfirmed unless a previous valid confirm exists. |

Summary:

```text
If no valid metadata exists:
  stay in bootloader

If latest metadata record is corrupted:
  ignore corrupted record and use previous valid record

If IMAGE_VALID exists but APP_CONFIRMED does not:
  limit boot attempts to boot_attempt_limit

If APP_CONFIRMED exists:
  boot App
```

## 18. FLASH_READ and GET_METADATA_SUMMARY Relationship

`docs/26_protocol_extension_for_reliability.md` defines:

```text
BOOT_CMD_FLASH_READ
BOOT_CMD_GET_METADATA_SUMMARY
```

Metadata raw read:

```text
BOOT_CMD_FLASH_READ
```

Parsed metadata summary:

```text
BOOT_CMD_GET_METADATA_SUMMARY
```

GUI should prefer:

```text
GET_METADATA_SUMMARY
```

for normal display.

GUI may use:

```text
FLASH_READ
```

for raw metadata debug view.

## 19. GUI Requirements

Future GUI should display:

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
slot_id
metadata record count
metadata free record count
metadata error status
```

GUI must reject firmware images that write into metadata area:

```text
0x082000 ~ 0x0823FF
```

GUI must treat valid App area as:

```text
0x082400 ~ 0x0BFFFF
```

GUI sector mask calculation must still include Flash B if App uses Flash B
remainder, but Program must not write metadata words.

GUI implementation must continue to use the PC IO Device abstraction.

## 20. DSP Requirements

Future DSP implementation must:

```text
1. Keep metadata parsing separate from raw protocol logic.
2. Keep Flash read/write permissions explicit.
3. Keep App Program range separate from metadata write range.
4. Reject App Program / Verify operations that touch metadata area.
5. Allow metadata write only through metadata-specific path.
6. Scan metadata journal at startup or on GET_METADATA_SUMMARY.
7. Validate record CRC32.
8. Select newest valid record by sequence.
9. Ignore corrupted or partially written record.
10. Stay in bootloader if metadata is invalid.
```

Codex must not implement low-level hardware init, PLL, Flash wait-state, raw
F021 API policy, DCSM, pump semaphore, or linker placement in this phase.

## 21. Future A/B Compatibility

Current stage does not implement A/B dual App.

The metadata format supports future A/B decisions with:

```text
slot_id
slot_role
app_start
app_end
entry_point
app_version
image_crc32
```

Future rule:

```text
If two slots are valid, bootloader may choose a slot using:
1. metadata validity
2. APP_CONFIRMED state
3. boot_attempt_count not exceeded
4. app version
```

Version comparison should use:

```text
major.minor.patch.build
```

Version is not the only priority. A lower-version confirmed App may be safer
than a higher-version unconfirmed App.

Future Slot B metadata location is reserved but not fixed. Do not assign a
fixed Slot B address in this document.

## 22. Deferred Items

The following items are explicitly deferred:

```text
1. Actual metadata implementation
2. Actual metadata Flash write code
3. Actual GUI metadata page
4. Actual App Confirm RAM function
5. Automatic boot decision integration in RAM bootloader
6. Flash-resident bootloader implementation
7. A/B dual App implementation
8. Slot B Flash layout
9. W5300 / TCP
10. CPU2 upgrade
11. Firmware signing
12. Encryption
13. DCSM unlock
14. Hardware maintenance mode
15. Automatic rollback
```

## 23. Open Questions

1. Should metadata record append be performed by the current Flash service lib
   or by a smaller dedicated metadata service path?
2. What exact App linker command change will reserve `0x082000 ~ 0x0823FF`
   while keeping the App entry point 8-word aligned?
3. Should `IMAGE_VALID` be appended by `ProgramEnd`, `VerifyEnd`, or a separate
   metadata-specific command after `VerifyEnd` succeeds?
4. Should `image_crc32` be rechecked by DSP before every boot, or only during
   explicit diagnostics / metadata summary refresh?
5. What journal-full policy should be used before automatic rollback exists?
