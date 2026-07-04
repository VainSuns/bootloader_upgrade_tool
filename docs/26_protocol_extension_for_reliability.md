# 26 Protocol Extension for Industrial Reliability

## 1. Purpose

This document defines protocol extensions for reliability work after v0.1.0.

The current v0.1.0 command semantics, frame format, and CRC16 framing remain
unchanged. The new command IDs, feature flags, status codes, and payload rules
prepare later implementation of:

- RAM service / Flash service verification.
- RAM App debug execution.
- Flash read operations.
- Metadata read and summary.
- App confirmation.
- Future CPU2 boot coordination.
- Future Flash-resident bootloader behavior.
- Future A/B App metadata.
- Industrial diagnostics and recovery.

## 2. Scope

This phase is documentation and design only.

This document does not implement:

- DSP protocol code.
- PC protocol code.
- GUI changes.
- metadata implementation.
- Flash read implementation.
- RAM check implementation.
- CPU2 IPC logic.
- App confirm logic.

The final long-term target remains a Flash-resident bootloader. Until the
industrial reliability mechanisms are validated, the project continues to use
the RAM bootloader for fast development and testing.

## 3. Existing Protocol Compatibility

Existing v0.1.0 protocol commands keep their current semantics:

```c
#define BOOT_CMD_PING              0x0001
#define BOOT_CMD_GET_DEVICE_INFO   0x0002
#define BOOT_CMD_GET_PROTOCOL_INFO 0x0003
#define BOOT_CMD_GET_LAST_ERROR    0x0004

#define BOOT_CMD_RAM_LOAD_BEGIN    0x0101
#define BOOT_CMD_RAM_LOAD_DATA     0x0102
#define BOOT_CMD_RAM_LOAD_END      0x0103

#define BOOT_CMD_ERASE             0x0201
#define BOOT_CMD_PROGRAM_BEGIN     0x0210
#define BOOT_CMD_PROGRAM_DATA      0x0211
#define BOOT_CMD_PROGRAM_END       0x0212
#define BOOT_CMD_VERIFY_BEGIN      0x0220
#define BOOT_CMD_VERIFY_DATA       0x0221
#define BOOT_CMD_VERIFY_END        0x0222

#define BOOT_CMD_RUN               0x0301
#define BOOT_CMD_RESET             0x0302
```

The existing protocol frame format remains unchanged:

```text
Word 0:  magic0
Word 1:  magic1
Word 2:  protocol_ver
Word 3:  packet_type
Word 4:  command
Word 5:  sequence
Word 6:  flags
Word 7:  status
Word 8:  payload_words
Word 9:  header_crc16
Word 10..N: payload
Last Word: payload_crc16
```

The existing protocol frame CRC16 mechanism remains unchanged. CRC32 introduced
in this document is only for reliability-related data checks such as RAM check,
metadata records, image CRC, and diagnostic memory or Flash checks.

SCI `'A'` autobaud remains a connection-layer operation, not a protocol frame.
The DSP remains the slave and the PC GUI remains the master. DSP must not send
asynchronous messages.

## 4. Command Group Layout

Command groups are reserved as follows:

```text
0x0001 ~ 0x00FF: Core / Protocol / Status
0x0101 ~ 0x01FF: RAM Load / RAM Check / RAM Debug
0x0201 ~ 0x02FF: Flash Service
0x0301 ~ 0x03FF: Run / CPU Transition / Reset
0x0401 ~ 0x04FF: Metadata / App Confirm
0x0501 ~ 0x05FF: Diagnostics / Recovery / Security
```

## 5. New Command ID Table

### Near-Term Commands

These commands are expected to be implemented earlier in Phase 10 after review:

| Command | ID | Group | Purpose |
|---|---:|---|---|
| `BOOT_CMD_GET_BOOT_STATUS` | `0x0005` | Core / Status | Return compact bootloader runtime status. |
| `BOOT_CMD_ABORT_SESSION` | `0x0006` | Core / Status | Clear interrupted volatile session state. |
| `BOOT_CMD_GET_SERVICE_STATUS` | `0x0007` | Core / Status | Report RAM service / Flash service status. |
| `BOOT_CMD_RAM_CHECK_CRC` | `0x0104` | RAM | Verify a RAM region against an expected CRC32. |
| `BOOT_CMD_FLASH_READ` | `0x0230` | Flash | Read allowed Flash ranges in chunks. |
| `BOOT_CMD_GET_METADATA_SUMMARY` | `0x0401` | Metadata | Return DSP-parsed metadata summary. |

```c
#define BOOT_CMD_GET_BOOT_STATUS             0x0005
#define BOOT_CMD_ABORT_SESSION               0x0006
#define BOOT_CMD_GET_SERVICE_STATUS          0x0007
#define BOOT_CMD_RAM_CHECK_CRC               0x0104
#define BOOT_CMD_FLASH_READ                  0x0230
#define BOOT_CMD_GET_METADATA_SUMMARY        0x0401
```

### Debug / Reserved Commands

These commands are design reservations or debug-only features:

| Command | ID | Group | Purpose |
|---|---:|---|---|
| `BOOT_CMD_RUN_RAM` | `0x0105` | RAM | Debug-only RAM App or diagnostic code execution. |
| `BOOT_CMD_BOOT_CPU2_RUN_CPU1` | `0x0303` | Run / CPU Transition | Ask CPU2 bootloader to run CPU2 App, then run CPU1 App. |
| `BOOT_CMD_BOOT_CPU2_RESET_CPU1` | `0x0304` | Run / CPU Transition | Ask CPU2 bootloader to run CPU2 App, then reset CPU1. |
| `BOOT_CMD_METADATA_APPEND_RECORD` | `0x0402` | Metadata | Reserved controlled metadata append. |
| `BOOT_CMD_APP_CONFIRM` | `0x0403` | Metadata | Confirm a successfully started App. |
| `BOOT_CMD_METADATA_CLEAR` | `0x0404` | Metadata | Debug / recovery metadata erase. |

```c
#define BOOT_CMD_RUN_RAM                     0x0105
#define BOOT_CMD_BOOT_CPU2_RUN_CPU1          0x0303
#define BOOT_CMD_BOOT_CPU2_RESET_CPU1        0x0304
#define BOOT_CMD_METADATA_APPEND_RECORD      0x0402
#define BOOT_CMD_APP_CONFIRM                 0x0403
#define BOOT_CMD_METADATA_CLEAR              0x0404
```

Do not define a generic `BOOT_CMD_BOOT_CPU2`. CPU2 commands do not include a
CPU2 entry point.

Unsupported or disabled commands return:

```text
BOOT_STATUS_UNSUPPORTED_FEATURE
```

Debug-only commands disabled in release builds may return:

```text
BOOT_STATUS_DEBUG_ONLY_COMMAND
```

## 6. Feature Flags

New feature flags are reserved as follows:

```c
#define BOOT_FEATURE_RAM_CHECK_CRC           (1UL << 10)
#define BOOT_FEATURE_RUN_RAM                 (1UL << 11)
#define BOOT_FEATURE_FLASH_READ              (1UL << 12)
#define BOOT_FEATURE_BOOT_CPU2_RUN_CPU1      (1UL << 13)
#define BOOT_FEATURE_BOOT_CPU2_RESET_CPU1    (1UL << 14)
#define BOOT_FEATURE_METADATA_SUMMARY        (1UL << 15)
#define BOOT_FEATURE_APP_CONFIRM             (1UL << 16)
#define BOOT_FEATURE_METADATA_CLEAR          (1UL << 17)
#define BOOT_FEATURE_ABORT_SESSION           (1UL << 18)
#define BOOT_FEATURE_SERVICE_STATUS          (1UL << 19)
```

Defining a feature flag does not enable the feature.

GUI must expose only features advertised by `DeviceInfo.feature_flags`. DSP must
reject disabled or unsupported commands even if a non-GUI host sends them.

The current v0.1.0 advertised capability set remains limited to:

```text
ERASE
PROGRAM
VERIFY
RUN
```

## 7. Status Codes

New reliability status codes are reserved as follows:

```c
#define BOOT_STATUS_CRC_MISMATCH             0x0030
#define BOOT_STATUS_METADATA_INVALID         0x0031
#define BOOT_STATUS_METADATA_FULL            0x0032
#define BOOT_STATUS_METADATA_WRITE_FAILED    0x0033
#define BOOT_STATUS_READ_NOT_ALLOWED         0x0034
#define BOOT_STATUS_SERVICE_NOT_READY        0x0035
#define BOOT_STATUS_BOOT_CPU2_FAILED         0x0036
#define BOOT_STATUS_APP_NOT_CONFIRMED        0x0037
#define BOOT_STATUS_ATTEMPT_LIMIT_REACHED    0x0038
#define BOOT_STATUS_DEBUG_ONLY_COMMAND       0x0039
#define BOOT_STATUS_IPC_TIMEOUT              0x003A
#define BOOT_STATUS_CPU2_NOT_READY           0x003B
#define BOOT_STATUS_CPU1_NOT_READY_TO_RUN    0x003C
#define BOOT_STATUS_SHARED_RAM_CONFLICT      0x003D
```

`BOOT_STATUS_IPC_TIMEOUT` is scoped to future CPU1-to-CPU2 IPC coordination
only. It must not be used for SCI, frame receive, GUI IO, Flash FSM, or general
bootloader timeout handling. General timeout handling remains local to the PC
GUI / IO layer or to a future watchdog/metadata recovery strategy.

## 8. CRC32 Definition

Reliability checks use CRC32/IEEE:

```text
poly   = 0xEDB88320
init   = 0xFFFFFFFF
xorout = 0xFFFFFFFF
```

Input order:

```text
Each 16-bit word is processed low byte first, then high byte.
```

CRC32 is used for:

```text
RAM_CHECK_CRC
metadata record CRC
image_crc32
diagnostic memory/Flash check
```

CRC32 does not replace the protocol frame CRC16.

## 9. image_crc32 Calculation Rule

`image_crc32` is calculated by the PC GUI.

It covers:

```text
All actual padded image words programmed to Flash.
```

It includes:

```text
0xFFFF padding inserted by the PC to satisfy 8-word Flash programming alignment.
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

Future designs may add a separate `slot_region_crc32` if full slot-region
checking is needed.

## 10. RAM_CHECK_CRC Command

```c
#define BOOT_CMD_RAM_CHECK_CRC 0x0104
```

Purpose:

```text
Verify that a RAM region contains the expected data.
```

Main use cases:

```text
1. Verify that Flash service lib was correctly downloaded to RAM.
2. Verify RAM App image before RUN_RAM.
3. Verify a specific RAM range for diagnostics.
```

This command is preferred over Flash Verify for validating RAM-loaded service
libraries.

Request payload:

```text
Word 0: target
Word 1: address_low
Word 2: address_high
Word 3: word_count_low
Word 4: word_count_high
Word 5: expected_crc32_low
Word 6: expected_crc32_high
Word 7: crc_type
Word 8: flags
```

Target values:

```c
#define BOOT_TARGET_RAM_APP        0x0002
#define BOOT_TARGET_RAM_SERVICE    0x0003
```

CRC type:

```c
#define BOOT_CRC_TYPE_CRC32_SIMPLE 0x0001
```

Response payload:

```text
Word 0: calculated_crc32_low
Word 1: calculated_crc32_high
Word 2: match
```

Rules:

```text
1. DSP validates RAM address range.
2. DSP computes CRC32 over the requested RAM range.
3. DSP returns calculated CRC32.
4. If calculated CRC differs from expected CRC, return BOOT_STATUS_CRC_MISMATCH.
5. This command must not modify RAM.
```

## 11. RUN_RAM Command

```c
#define BOOT_CMD_RUN_RAM 0x0105
```

Purpose:

```text
Debug-only command for running RAM App or temporary RAM diagnostic code.
```

Request payload:

```text
Word 0: target
Word 1: entry_point_low
Word 2: entry_point_high
Word 3: flags
```

Target values:

```text
BOOT_TARGET_RAM_APP
BOOT_TARGET_RAM_SERVICE
```

Rules:

```text
1. Entry point must be inside an allowed RAM execution region.
2. Unlike Flash Run, RAM Run does not require Flash 8-word entry alignment.
3. DSP must send OK response first.
4. DSP must flush SCI TX before jumping.
5. DSP must reject this command unless RUN_RAM feature is advertised.
6. Release builds may keep this command disabled.
```

## 12. FLASH_READ Command

```c
#define BOOT_CMD_FLASH_READ 0x0230
```

Purpose:

```text
Read Flash contents for metadata display and debug diagnostics.
```

Main use cases:

```text
1. Read metadata records.
2. Read App Flash for debugging.
3. Support GUI metadata inspection.
```

Request payload:

```text
Word 0: read_target
Word 1: address_low
Word 2: address_high
Word 3: word_count
Word 4: flags
```

Read target values:

```c
#define BOOT_READ_TARGET_METADATA   0x0001
#define BOOT_READ_TARGET_APP        0x0002
#define BOOT_READ_TARGET_RAW_FLASH  0x0003
```

Response payload:

```text
Word 0: address_low
Word 1: address_high
Word 2: word_count
Word 3..N: data words
```

Rules:

```text
1. Flash Read is chunk-based.
2. Do not design READ_BEGIN / READ_DATA / READ_END in this phase.
3. PC should repeatedly call FLASH_READ for large reads.
4. word_count must be > 0.
5. word_count must be <= max_read_words.
6. max_read_words = max_payload_words - 3.
7. Metadata read is allowed when address is inside metadata region.
8. App read is allowed only when metadata is valid.
9. RAW_FLASH read is debug-only and disabled by default.
10. Sector A / bootloader read is disabled by default.
```

If reading App while metadata is invalid, return:

```text
BOOT_STATUS_METADATA_INVALID
```

If reading outside the permitted range, return:

```text
BOOT_STATUS_READ_NOT_ALLOWED
```

## 13. GET_BOOT_STATUS Command

```c
#define BOOT_CMD_GET_BOOT_STATUS 0x0005
```

Purpose:

```text
Return bootloader runtime status in a compact form.
```

Response payload:

```text
Word 0: boot_state
Word 1: active_slot
Word 2: metadata_valid
Word 3: app_confirmed
Word 4: boot_attempt_count
Word 5: service_loaded
Word 6: last_fault_stage
Word 7: flags
```

GUI uses:

```text
Display current bootloader state.
Display metadata validity.
Display current active slot.
Display app confirmed state.
Display service loaded status.
Display fault summary.
```

## 14. ABORT_SESSION Command

```c
#define BOOT_CMD_ABORT_SESSION 0x0006
```

Purpose:

```text
Clear current protocol/service session state after a failed or interrupted operation.
```

It should reset:

```text
RAM_LOAD session
PROGRAM session
VERIFY session
metadata session
temporary service session state
```

Response:

```text
OK
```

Rules:

```text
1. Must not erase Flash.
2. Must not modify metadata.
3. Must not clear persistent fault records.
4. Should be safe to call multiple times.
```

## 15. GET_SERVICE_STATUS Command

```c
#define BOOT_CMD_GET_SERVICE_STATUS 0x0007
```

Purpose:

```text
Report status of RAM service lib / Flash service lib.
```

Response payload:

```text
Word 0: service_active
Word 1: service_image_ready
Word 2: service_abi_major
Word 3: service_abi_minor
Word 4: service_crc32_low
Word 5: service_crc32_high
Word 6: service_entry_low
Word 7: service_entry_high
```

Relationship to `RAM_CHECK_CRC`:

```text
RAM_CHECK_CRC validates RAM bytes/words.
GET_SERVICE_STATUS reports whether the service is recognized, attached, and usable.
```

## 16. GET_METADATA_SUMMARY Command

```c
#define BOOT_CMD_GET_METADATA_SUMMARY 0x0401
```

Purpose:

```text
Return DSP-parsed metadata summary.
```

This is different from `FLASH_READ`. `FLASH_READ` returns raw Flash words.
`GET_METADATA_SUMMARY` returns the bootloader's interpretation of metadata.

Response payload:

```text
Word 0: metadata_valid
Word 1: active_slot
Word 2: latest_record_type
Word 3: boot_attempt_count
Word 4: app_confirmed
Word 5: app_version_major
Word 6: app_version_minor
Word 7: app_version_patch
Word 8: app_version_build_low
Word 9: app_version_build_high
Word 10: entry_point_low
Word 11: entry_point_high
Word 12: image_crc32_low
Word 13: image_crc32_high
Word 14: flags
```

Rules:

```text
1. DSP scans metadata journal.
2. DSP validates record CRC32.
3. DSP selects newest valid record by sequence number.
4. DSP returns parsed summary.
5. GUI should prefer GET_METADATA_SUMMARY for normal display.
6. GUI may use FLASH_READ for raw debug view.
```

## 17. Metadata Command Placeholders

### METADATA_APPEND_RECORD

```c
#define BOOT_CMD_METADATA_APPEND_RECORD 0x0402
```

Purpose:

```text
Reserved for future controlled metadata record append.
```

Current phase:

```text
Define only.
Do not implement general GUI arbitrary metadata writing.
Feature flag should remain disabled.
```

Future rules:

```text
1. Not for arbitrary host writes in production.
2. May be used by controlled bootloader flow.
3. May be disabled in release build.
```

### METADATA_CLEAR

```c
#define BOOT_CMD_METADATA_CLEAR 0x0404
```

Purpose:

```text
Debug / recovery command to clear metadata.
```

Current phase:

```text
Define only.
Do not expose in normal GUI.
```

Rules:

```text
1. Dangerous command.
2. Must require advanced/debug mode.
3. Must only erase metadata area.
4. Must not erase App data outside metadata area.
5. Must be hidden unless feature flag is advertised.
```

## 18. App Confirm Command

```c
#define BOOT_CMD_APP_CONFIRM 0x0403
```

Purpose:

```text
Confirm that App has successfully started and is running correctly.
```

Current decision:

```text
App Confirm is designed now but not required to be fully implemented immediately.
Preferred future implementation is a bootloader-provided confirm function.
The confirm function can be placed in RAM together with the Flash service lib.
```

Request payload:

```text
Word 0: slot_id
Word 1: image_crc32_low
Word 2: image_crc32_high
Word 3: flags
```

Response:

```text
OK
METADATA_INVALID
CRC_MISMATCH
METADATA_FULL
METADATA_WRITE_FAILED
UNSUPPORTED_FEATURE
```

Future behavior:

```text
1. App calls bootloader-provided confirm function after successful initialization.
2. Confirm function appends APP_CONFIRMED metadata record.
3. Bootloader later treats the App as confirmed.
```

## 19. CPU2 Boot Coordination Commands

CPU2 boot coordination uses two protocol-reserved commands:

```c
#define BOOT_CMD_BOOT_CPU2_RUN_CPU1    0x0303
#define BOOT_CMD_BOOT_CPU2_RESET_CPU1  0x0304
```

These commands are protocol reservations only. Do not implement CPU2 IPC logic
in this phase. Do not include a CPU2 entry point in either command.

Important CPU2 design rule:

```text
CPU2 bootloader is assumed to be already running.
CPU1 bootloader does not specify CPU2 entry point.
CPU1 bootloader only sends an IPC command to CPU2 bootloader.
CPU2 bootloader is responsible for selecting and running CPU2 App according to
CPU2 metadata or CPU2 boot policy.
```

### BOOT_CPU2_RUN_CPU1

Semantic flow:

```text
1. PC sends BOOT_CPU2_RUN_CPU1 to CPU1 bootloader.
2. CPU1 bootloader sends IPC command to CPU2 bootloader.
3. CPU2 bootloader completes CPU2 App boot flow.
4. CPU2 sends IPC command back to CPU1.
5. CPU1 runs CPU1 App.
```

Request payload:

```text
Word 0: target_cpu, must be BOOT_CPU2
Word 1: cpu2_boot_policy
Word 2: cpu2_slot_id
Word 3: cpu1_run_policy
Word 4: flags
```

No CPU2 entry point is included.

### BOOT_CPU2_RESET_CPU1

Semantic flow:

```text
1. PC sends BOOT_CPU2_RESET_CPU1 to CPU1 bootloader.
2. CPU1 bootloader sends IPC command to CPU2 bootloader.
3. CPU2 bootloader completes CPU2 boot flow.
4. CPU2 sends IPC command back to CPU1.
5. CPU1 resets CPU1.
```

Request payload:

```text
Word 0: target_cpu, must be BOOT_CPU2
Word 1: cpu2_boot_policy
Word 2: cpu2_slot_id
Word 3: cpu1_reset_policy
Word 4: flags
```

No CPU2 entry point is included.

CPU2 boot commands must be rejected if any of the following are active:

```text
Erase session
Program session
Verify session
RAM_LOAD session
metadata write session
Flash service operation
RAM service operation
```

Return:

```text
BOOT_STATUS_BUSY
```

or:

```text
BOOT_STATUS_INVALID_STATE
```

CPU2 boot commands must be allowed only after CPU1 boot/update flow has
completed.

Reason:

```text
CPU2 App may access shared RAM or IPC resources.
CPU2 App may conflict with CPU1 bootloader RAM service or Flash service.
Therefore CPU2 must not be started while CPU1 bootloader service code is still active.
```

Current phase behavior:

```text
Return BOOT_STATUS_UNSUPPORTED_FEATURE.
GUI must not expose CPU2 features.
```

## 20. Access Control and Debug-Only Behavior

Every new command must be gated by feature flags.

Recommended behavior:

```text
If command is known but feature disabled:
  BOOT_STATUS_UNSUPPORTED_FEATURE

If command is debug-only and disabled in release:
  BOOT_STATUS_DEBUG_ONLY_COMMAND

If command is valid but current state does not permit it:
  BOOT_STATUS_INVALID_STATE or BOOT_STATUS_BUSY
```

`DeviceInfo.feature_flags` is the GUI exposure contract, not a security
boundary. DSP must still reject unsupported, disabled, invalid-state, or
debug-only commands from any host.

## 21. GUI Requirements

Future GUI behavior:

```text
1. Display DeviceInfo feature flags.
2. Show RAM_CHECK_CRC capability if available.
3. Show Flash Read / Metadata Read capability if available.
4. Prefer GET_METADATA_SUMMARY for normal metadata display.
5. Use FLASH_READ only for raw metadata debug display.
6. Hide RUN_RAM unless debug feature is advertised.
7. Hide CPU2 commands unless CPU2 feature flags are advertised.
8. Hide METADATA_CLEAR unless advanced/debug mode is enabled.
9. Show service status when GET_SERVICE_STATUS is available.
10. Support ABORT_SESSION for recovery from interrupted PC-side workflows.
```

GUI implementation must continue to use the IO Device abstraction. It must not
directly depend on pySerial, sockets, or transport-specific behavior.

## 22. DSP Implementation Notes

Implementation principles:

```text
1. Do not modify existing protocol frame format.
2. Do not change existing command semantics.
3. New commands must be added with feature gating.
4. New large read operations must be chunk-based.
5. No READ_BEGIN / READ_DATA / READ_END for Flash Read in this phase.
6. RAM_CHECK_CRC must not modify RAM.
7. FLASH_READ must not bypass metadata or range permissions.
8. Metadata commands must not allow arbitrary unsafe Flash writes.
9. CPU2 commands are protocol reservations only.
10. App Confirm should be designed for future bootloader-provided RAM function.
```

Codex must not implement low-level DSP system init, PLL, Flash wait-state, raw
F021 API, DCSM, pump semaphore, or linker placement. Hardware-dependent DSP
work should stay in user-port templates.

Flash/RAM behavior must preserve the Flash-resident core / RAM-resident service
lib split. `RAM_CHECK_CRC` is a RAM verification primitive, not a substitute for
Flash Verify. `FLASH_READ` is a read primitive, not a write or metadata mutation
path.

## 23. Deferred Items

The following items are explicitly deferred:

```text
1. Actual CPU2 IPC logic
2. Actual App Confirm implementation
3. W5300 / TCP
4. CPU2 upgrade
5. A/B dual App implementation
6. Firmware signing
7. Encryption
8. DCSM unlock
9. Hardware maintenance mode
10. GUI Reset button
11. Automatic rollback
```

Debug / reserved commands must not be advertised by `DeviceInfo.feature_flags`
until their behavior is implemented and tested.

## 24. Open Questions

1. Should the extension status codes remain in the low `0x0030` range, or be
   moved into the existing grouped status-code ranges before implementation?
2. What exact metadata Flash region and record format will be used for v0.2?
3. What maximum `FLASH_READ` chunk size should be advertised for hardware and
   GUI usability?
4. Which build profile, if any, may enable `RUN_RAM` or `RAW_FLASH` debug read?
5. What is the final service ABI versioning rule for `GET_SERVICE_STATUS`?
6. What CPU2 IPC timeout and retry policy is acceptable for future dual-core
   boot coordination?
