# 14 Communication Protocol Specification

Version: v0.1 frozen draft  
Target: DSP28377D bootloader online upgrade protocol

## 1. Basic Model

```text
PC GUI = master
DSP bootloader = slave
```

DSP never sends asynchronous messages. Every transaction is:

```text
PC request -> DSP response
```

## 2. Word Stream and Endianness

The formal protocol is a 16-bit word stream. A word is serialized little-endian:

```text
word 0xA55A -> bytes 0x5A, 0xA5
```

SCI/UART wire transport is an 8-bit byte stream. Receiver synchronization must
search raw bytes for `5A A5 A5 5A`; only after finding this sequence may it
reconstruct little-endian 16-bit words.

## 3. Connection Layer

SCI autobaud `'A'` handshake is outside formal protocol.

DSP IO:

```c
BootIo_GetByte(ctx)
BootIo_GetWord(ctx)
BootIo_SendWord(ctx, word)
```

`get_byte` is blocking and has no timeout parameter. It is required for receive
resynchronization. Sending remains word-based through `BootIo_SendWord`.
Timeout handling remains in the connection flow or an upper-level state machine.

PC IO:

```python
open()
wait_slave(timeout_ms)
read_available()
read_word(timeout_ms)
write_word(word)
close()
```

For SCI on Windows USB-RS232 adapters, PC response receive must poll
`in_waiting`, read all currently pending bytes, accumulate them in a byte
buffer, and extract frames by searching raw bytes for `5A A5 A5 5A`. Do not
implement the SCI protocol receive path as repeated `serial.read(1)` calls with
changing timeouts.

## 4. Frame Layout

```text
Word 0:  magic0          = 0xA55A
Word 1:  magic1          = 0x5AA5
Word 2:  protocol_ver    = 0x0001
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

## 5. CRC

CRC is CRC-16/CCITT-FALSE:

```text
poly   = 0x1021
init   = 0xFFFF
refin  = false
refout = false
xorout = 0x0000
check  = 0x29B1 for "123456789"
```

CRC input is the actual little-endian byte stream generated from words.

```text
header_crc16 = CRC16(Word 0..Word 8)
payload_crc16 = CRC16(payload words)
```

If `payload_words = 0`, `payload_crc16 = CRC16(empty)`.

## 6. Packet Types

```c
#define BOOT_PKT_REQUEST        0x0001
#define BOOT_PKT_RESPONSE       0x0002
#define BOOT_PKT_ERROR_RESPONSE 0x0003
```

No DATA packet type.

## 7. Flags

MVP flags must be zero.

```c
#define BOOT_FLAG_NONE 0x0000
```

If any frame-level or payload-level flags field is nonzero in MVP, DSP returns:

```c
#define BOOT_STATUS_BAD_FLAGS 0x0109
```

## 8. 32-bit Field Rule

All 32-bit fields are low word first, high word second.

```c
value = ((uint32_t)high << 16) | low;
```

## 9. Sequence

- 16-bit unsigned;
- PC starts from 1;
- 0 is reserved;
- increment per request;
- overflow wraps to 1;
- response sequence must equal request sequence.

## 10. Data Alignment Rules

Flash ProgramData / VerifyData payloads must satisfy:

```text
data_words > 0
data_words % 8 == 0
data_words <= max_data_words
```

This applies to:

```text
ProgramData.data[]
VerifyData.expected_data[]
```

The PC side must pad tail data with `0xFFFF` before transmission.

If `data_words` is not a multiple of 8, DSP must reject the packet with:

```c
BOOT_STATUS_BAD_WORD_COUNT
```

RamLoadData is RAM, not Flash. It has no 8-byte or 8-word alignment
requirement. RAM load only requires `data_words > 0`, valid payload length, no
address wrap, and the full `[address, address + data_words)` interval inside one
generated RAM write region.

## 11. Commands

### Core

```c
#define BOOT_CMD_PING              0x0001
#define BOOT_CMD_GET_DEVICE_INFO   0x0002
#define BOOT_CMD_GET_PROTOCOL_INFO 0x0003
#define BOOT_CMD_GET_LAST_ERROR    0x0004
#define BOOT_CMD_GET_SERVICE_STATUS 0x0007
#define BOOT_CMD_SERVICE_ATTACH    0x0008
```

### RAM Load

```c
#define BOOT_CMD_RAM_LOAD_BEGIN    0x0101
#define BOOT_CMD_RAM_LOAD_DATA     0x0102
#define BOOT_CMD_RAM_LOAD_END      0x0103
#define BOOT_CMD_RAM_CHECK_CRC     0x0104
#define BOOT_CMD_RUN_RAM           0x0105
```

No `RamServiceActivate`.

### Downloaded Service Attach

`SERVICE_ATTACH` is separate from `RUN_RAM`. It validates a RAM-loaded service
descriptor and attaches the service through `BootServiceApi`; it does not jump
to service code and does not write metadata.

Request payload:

```text
descriptor_address_low
descriptor_address_high
expected_crc32_low
expected_crc32_high
expected_total_words_low
expected_total_words_high
flags = 0
```

`GET_SERVICE_STATUS` response payload is exactly 12 words:

```text
service_state
abi_major
abi_minor
service_major
service_minor
capabilities_low
capabilities_high
last_attach_status
loaded_image_crc32_low
loaded_image_crc32_high
loaded_image_words_low
loaded_image_words_high
```

Service states:

```c
#define BOOT_SERVICE_STATE_DETACHED   0x0000
#define BOOT_SERVICE_STATE_RAM_LOADED 0x0001
#define BOOT_SERVICE_STATE_ATTACHED   0x0002
#define BOOT_SERVICE_STATE_ERROR      0x0003
```

The service descriptor is 20 words:

```text
0-1  descriptor_magic
2    descriptor_version
3    descriptor_words
4    abi_major
5    abi_minor
6    service_major
7    service_minor
8-9  api_table_address
10-11 image_start
12-13 image_end_exclusive
14-15 image_crc32
16-17 capabilities
18-19 descriptor_crc32 over words 0..17
```

### Flash

```c
#define BOOT_CMD_ERASE             0x0201
#define BOOT_CMD_PROGRAM_BEGIN     0x0210
#define BOOT_CMD_PROGRAM_DATA      0x0211
#define BOOT_CMD_PROGRAM_END       0x0212
#define BOOT_CMD_VERIFY_BEGIN      0x0220
#define BOOT_CMD_VERIFY_DATA       0x0221
#define BOOT_CMD_VERIFY_END        0x0222
```

### Metadata

```c
#define BOOT_CMD_GET_METADATA_SUMMARY   0x0401
#define BOOT_CMD_METADATA_APPEND_RECORD 0x0402
```

Future reserved:

```c
#define BOOT_CMD_APP_CONFIRM 0x0403
```

`BOOT_CMD_APP_CONFIRM` is reserved for future debug/App-confirm support. It is
not implemented in Phase 10.2I and must not be exposed as an active command.

`GET_METADATA_SUMMARY` returns parsed Slot A metadata summary.

`METADATA_APPEND_RECORD` currently supports:

```text
IMAGE_VALID
BOOT_ATTEMPT
```

`APP_CONFIRMED` is reserved for a later phase and is not implemented yet.

### Run/Reset

```c
#define BOOT_CMD_RUN               0x0301
#define BOOT_CMD_RESET             0x0302
```

## 12. Status Codes

```c
#define BOOT_STATUS_OK                         0x0000

#define BOOT_STATUS_BAD_PAYLOAD_CRC            0x0103
#define BOOT_STATUS_UNSUPPORTED_PROTOCOL       0x0104
#define BOOT_STATUS_BAD_PACKET_TYPE            0x0105
#define BOOT_STATUS_BAD_PAYLOAD_LENGTH         0x0106
#define BOOT_STATUS_BAD_FLAGS                  0x0109

#define BOOT_STATUS_UNKNOWN_COMMAND            0x0201
#define BOOT_STATUS_UNSUPPORTED_COMMAND        0x0202
#define BOOT_STATUS_INVALID_STATE              0x0203
#define BOOT_STATUS_BUSY                       0x0204
#define BOOT_STATUS_MISSING_BEGIN              0x0205
#define BOOT_STATUS_UNEXPECTED_END             0x0206
#define BOOT_STATUS_BLOCK_INDEX_ERROR          0x0207
#define BOOT_STATUS_TOTAL_COUNT_MISMATCH       0x0208

#define BOOT_STATUS_BAD_ADDRESS                0x0301
#define BOOT_STATUS_ADDRESS_OUT_OF_RANGE       0x0302
#define BOOT_STATUS_BAD_ALIGNMENT              0x0303
#define BOOT_STATUS_BAD_WORD_COUNT             0x0304
#define BOOT_STATUS_PROTECTED_REGION           0x0305

#define BOOT_STATUS_ERASE_FAILED               0x0401
#define BOOT_STATUS_ERASE_FSM_ERROR            0x0402
#define BOOT_STATUS_BLANK_CHECK_FAILED         0x0403

#define BOOT_STATUS_PROGRAM_FAILED             0x0501
#define BOOT_STATUS_PROGRAM_FSM_ERROR          0x0502
#define BOOT_STATUS_PROGRAM_VERIFY_FAILED      0x0503
#define BOOT_STATUS_REPROGRAM_FORBIDDEN        0x0504

#define BOOT_STATUS_VERIFY_FAILED              0x0601
#define BOOT_STATUS_VERIFY_MISMATCH            0x0602

#define BOOT_STATUS_RAM_ADDRESS_ERROR          0x0701
#define BOOT_STATUS_RAM_WRITE_FAILED           0x0702
#define BOOT_STATUS_RAM_REGION_ERROR           0x0703

#define BOOT_STATUS_UNSUPPORTED_FEATURE        0x0801
#define BOOT_STATUS_DEVICE_INFO_UNAVAILABLE    0x0802
#define BOOT_STATUS_TARGET_MISMATCH            0x0803
#define BOOT_STATUS_METADATA_INVALID           0x0804
#define BOOT_STATUS_METADATA_FULL              0x0805
#define BOOT_STATUS_METADATA_WRITE_FAILED      0x0806
#define BOOT_STATUS_ATTEMPT_LIMIT_REACHED      0x0807

#define BOOT_STATUS_SECURITY_LOCKED            0x0901
#define BOOT_STATUS_UNLOCK_FAILED              0x0902

#define BOOT_STATUS_USER_ERROR_BASE            0x7F00
```

No timeout status code. Timeout is GUI/IO local error.

The following conditions are also handled as receiver-side local diagnostics and are not guaranteed to be returned as DSP response status codes:

```text
bad magic
bad header CRC
GUI response sequence mismatch
```

DSP request header CRC failure causes resync and no response. GUI response sequence mismatch is a GUI local error.

## 13. Feature Flags

```c
#define BOOT_FEATURE_ERASE             (1U << 0)
#define BOOT_FEATURE_PROGRAM           (1U << 1)
#define BOOT_FEATURE_VERIFY            (1U << 2)
#define BOOT_FEATURE_RUN               (1U << 3)
#define BOOT_FEATURE_RESET             (1U << 4)
#define BOOT_FEATURE_RAM_LOAD          (1U << 5)
#define BOOT_FEATURE_APP_UPLOAD        (1U << 6)
#define BOOT_FEATURE_METADATA          (1U << 7)
#define BOOT_FEATURE_UNLOCK_Z1         (1U << 8)
#define BOOT_FEATURE_UNLOCK_Z2         (1U << 9)
```

## 14. DeviceInfo Payload, 16 words

```text
Word 0:  device_id
Word 1:  cpu_id
Word 2:  kernel_ver_major
Word 3:  kernel_ver_minor
Word 4:  kernel_ver_patch
Word 5:  protocol_ver
Word 6:  feature_flags_low
Word 7:  feature_flags_high
Word 8:  max_payload_words
Word 9:  max_data_words
Word 10: boot_mode
Word 11: kernel_layout
Word 12: revision_id_low
Word 13: revision_id_high
Word 14: uid_unique_low
Word 15: uid_unique_high
```

```c
#define BOOT_DEVICE_UNKNOWN        0x0000
#define BOOT_DEVICE_F28377D        0x377D

#define BOOT_CPU_UNKNOWN           0x0000
#define BOOT_CPU1                  0x0001
#define BOOT_CPU2                  0x0002

#define BOOT_MODE_UNKNOWN          0x0000
#define BOOT_MODE_RAM_KERNEL       0x0001
#define BOOT_MODE_FLASH_KERNEL     0x0002

#define BOOT_KERNEL_LAYOUT_UNKNOWN       0x0000
#define BOOT_KERNEL_LAYOUT_MONOLITHIC    0x0001
#define BOOT_KERNEL_LAYOUT_CORE_RAM_LIB  0x0002
```

Additional DeviceInfo rule:

```text
max_data_words > 0
max_data_words must be a multiple of 8
max_data_words + 5 <= max_payload_words
```

The five-word allowance covers address, data_words, and block_index metadata in
ProgramData / VerifyData. RamLoadData uses the same five metadata words but does
not use the Flash-specific `max_data_words` alignment contract.

DSP internal `BootDeviceInfo` stores complete PARTIDL, PARTIDH, REVID,
UID_UNIQUE, UID_CHECKSUM, and UID_PSRAND0..5 identity. GetDeviceInfo v1 remains
fixed at 16 words and exports only REVID and UID_UNIQUE. Full identity export is
Future work through a separate command such as GetExtendedDeviceInfo.

## 15. ProtocolInfo Payload, 8 words

```text
Word 0: protocol_ver
Word 1: min_supported_ver
Word 2: max_supported_ver
Word 3: header_words
Word 4: crc_type
Word 5: endian
Word 6: max_payload_words
Word 7: flags
```

```c
#define BOOT_HEADER_WORDS            10
#define BOOT_CRC_TYPE_CCITT_FALSE    0x0001
#define BOOT_ENDIAN_LITTLE           0x0001
```

## 16. ErrorDetail Payload, 11 words

```text
Word 0:  error_operation
Word 1:  error_stage
Word 2:  address_low
Word 3:  address_high
Word 4:  length_words_low
Word 5:  length_words_high
Word 6:  api_status
Word 7:  fsm_status_low
Word 8:  fsm_status_high
Word 9:  extra0
Word 10: extra1
```

```c
#define BOOT_ERR_OP_NONE         0x0000
#define BOOT_ERR_OP_FRAME        0x0001
#define BOOT_ERR_OP_ERASE        0x0002
#define BOOT_ERR_OP_PROGRAM      0x0003
#define BOOT_ERR_OP_VERIFY       0x0004
#define BOOT_ERR_OP_RAM_LOAD     0x0005
#define BOOT_ERR_OP_RUN          0x0006
#define BOOT_ERR_OP_RESET        0x0007

#define BOOT_ERR_STAGE_NONE          0x0000
#define BOOT_ERR_STAGE_HEADER        0x0001
#define BOOT_ERR_STAGE_PAYLOAD       0x0002
#define BOOT_ERR_STAGE_ADDRESS_CHECK 0x0003
#define BOOT_ERR_STAGE_API_CALL      0x0004
#define BOOT_ERR_STAGE_FSM           0x0005
#define BOOT_ERR_STAGE_VERIFY        0x0006
#define BOOT_ERR_STAGE_STATE         0x0007
```

Protocol/header/framing-level ERROR_RESPONSE frames carry no ErrorDetail
payload. ErrorDetail is reserved for meaningful operation-level failures such
as Erase/Program/Verify/RAM operations, and GetLastError queries the latest such
operation detail.

## 17. Erase Payload

```text
Word 0: sector_mask_low
Word 1: sector_mask_high
Word 2: flags
```

Rules:

- only SECTOR_MASK mode;
- sector bit order equals `device_info.json.flash_sectors` order;
- Erase flags must be 0;
- DSP does not retry internally;
- GUI retry is external workflow.

## 18. ProgramBegin Payload, 9 words

```text
Word 0:  program_target
Word 1:  block_count
Word 2:  total_words_low
Word 3:  total_words_high
Word 4:  entry_point_low
Word 5:  entry_point_high
Word 6:  image_crc_low
Word 7:  image_crc_high
Word 8:  flags
```

MVP `image_crc` may be 0. Flags must be 0.

`ProgramBegin.program_target` currently supports only:

```c
#define BOOT_TARGET_FLASH_APP   0x0001
```

RAM writes must use `RamLoadBegin / RamLoadData / RamLoadEnd`, not `ProgramBegin`.

`BOOT_TARGET_RAM_APP = 0x0002` is reserved for `Run.target_type` and future RAM-related flows. It is not valid for `ProgramBegin` in MVP.

## 19. ProgramData Payload

```text
Word 0: address_low
Word 1: address_high
Word 2: data_words
Word 3: block_index_low
Word 4: block_index_high
Word 5..: data[0 .. data_words - 1]
```

Rules:

- ProgramBegin must be active;
- `payload_words = 5 + data_words`;
- `data_words % 8 == 0`;
- block_index starts at 0 and strictly increments;
- address is explicit;
- block_index is not used for address calculation;
- Program failure ends program session;
- ProgramData timeout must not be retried.

## 20. ProgramEnd Payload, 6 words

```text
Word 0: total_packets_low
Word 1: total_packets_high
Word 2: total_words_low
Word 3: total_words_high
Word 4: final_crc_low
Word 5: final_crc_high
```

MVP `final_crc` may be 0.

Count mismatch returns `BOOT_STATUS_TOTAL_COUNT_MISMATCH` and ends program session.

## 21. VerifyBegin / VerifyData / VerifyEnd

Verify payloads mirror Program payloads.

Verify failure ends verify session.

## 22. Run Payload

```text
Word 0: target_type
Word 1: entry_point_low
Word 2: entry_point_high
Word 3: flags
```

Run target constants:

```c
#define BOOT_TARGET_FLASH_APP   0x0001
#define BOOT_TARGET_RAM_APP     0x0002
```

FLASH_APP requires entry point in flash app range and 8-word aligned. GUI and DSP both check. RAM_APP does not require 8-word entry alignment.

DSP sends OK response first, then returns RUN_APP action to outer layer.

## 23. Reset

Payload is empty. DSP sends OK response first, then returns RESET_DEVICE action to outer layer.

## 24. RamLoad / RunRam Payloads

RamLoadBegin:

```text
Word 0: ram_region_type
Word 1: block_count
Word 2: total_words_low
Word 3: total_words_high
Word 4: entry_point_low
Word 5: entry_point_high
Word 6: image_crc_low
Word 7: image_crc_high
Word 8: flags
```

RamLoadData:

```text
Word 0: address_low
Word 1: address_high
Word 2: data_words
Word 3: block_index_low
Word 4: block_index_high
Word 5..: data[0 .. data_words - 1]
```

`data_words` may be any positive 16-bit word count. No Flash-style 8-word
alignment applies to RamLoadData.

RamLoadEnd:

```text
Word 0: total_packets_low
Word 1: total_packets_high
Word 2: total_words_low
Word 3: total_words_high
Word 4: final_crc_low
Word 5: final_crc_high
```

No activate command.

RamCheckCrc:

```text
Word 0: expected_crc32_low
Word 1: expected_crc32_high
Word 2: expected_total_words_low
Word 3: expected_total_words_high
Word 4: flags
```

Rules:

- flags must be 0;
- RAM image must have completed RamLoadEnd;
- CRC32 is CRC32/IEEE over the exact 16-bit words sent in RamLoadData, low byte
  first then high byte;
- mismatch returns `BOOT_STATUS_VERIFY_MISMATCH`.

RunRam:

```text
Word 0: entry_point_low
Word 1: entry_point_high
Word 2: flags
```

Rules:

- flags must be 0;
- entry point 0 means use the loaded image entry point;
- RAM_CHECK_CRC must have passed after RAM_LOAD;
- entry point must be inside the loaded RAM image and allowed executable RAM;
- no Flash 8-word alignment rule applies;
- no metadata is written;
- DSP sends OK response first, then returns a RUN_RAM action to user layer.

## 25. Resync

Receiver performs sliding byte-level resync for wire magic `5A A5 A5 5A`.
Stale autobaud bytes, a wrong second magic byte, header CRC failure, or oversized
payload length resumes raw-byte search without assuming the candidate frame can
be consumed. Payload CRC failure on request returns BAD_PAYLOAD_CRC. Response
CRC failure is GUI local error.

If `payload_words > max_payload_words`, DSP does not guarantee error response and may directly resync.

`BOOT_STATUS_BAD_PAYLOAD_LENGTH` is used only when the header is valid and the payload can be safely consumed, or when malformed payload length is detected inside a valid command. If `payload_words` exceeds `max_payload_words`, DSP may resync without response.

## 26. GUI Timeout

Timeout is a GUI local error. GUI may send Ping to probe. If command may modify Flash/RAM, state remains unknown even if Ping succeeds.

## 27. ACK/NAK

No ACK/NAK words. All responses are full frames.
