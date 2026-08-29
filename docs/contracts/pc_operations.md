# PC Operation Library Contract

## 1. Authority and scope

This document defines the current long-term PC operation-library layers, public
APIs, atomic operation semantics, result and progress models, cancellation,
service runtime, metadata writes, image materialization, and target dispatch.

- [`runtime_architecture.md`](runtime_architecture.md) is authoritative for Runtime ownership, lifecycle, Evidence, and GUI dependency direction.
- This document is authoritative for operation-level admission and sequencing.
- Command IDs, frame format, payloads, and protocol statuses are defined by [`communication_protocol.md`](communication_protocol.md).
- GUI layout and visual structure are outside this document.

The operation library provides target-driven atomic actions. It does not own
GUI state, choose a workflow from CPU names, or turn atomic actions into hidden
compound behavior.

## 2. Layering and dependency direction

```text
GUI / CLI / Runtime caller
  -> operations public APIs
  -> OperationContext / FlashOperationContext
  -> active TargetProfile / CommandSet / memory map
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

PC-only image preparation is separate:

```text
AppResourceProvider or user-selected source
  -> images preparation/materialization
  -> immutable Prepared*Image
  -> operation request
```

Rules:

- operations obtain commands from `ctx.target.command_set`;
- address and sector validation use `ctx.target.memory_map`;
- no operation branches on `target.name`, `"cpu1"`, or `"cpu2"`;
- the current CPU1 capability does not authorize CPU1-specialized shared operation flow;
- an unsupported Target is rejected by a missing command, capability, layout,
  service compatibility, or Profile;
- CPU1 defaults must not fill missing CPU2 behavior.

## 3. Transport, protocol, and session

### 3.1 ByteTransport

`ByteTransport` exposes only byte-stream lifecycle and IO:

```python
open(cancellation=None) -> TransportOpenResult
close() -> None
write_all(data: bytes) -> None
read_some(max_bytes: int) -> bytes
```

`write_all()` writes all bytes and flushes; `read_some()` may short-read.
`SerialTransport.open()` owns SCI `A` autobaud and connection timing.
Autobaud is not a protocol command.

`TransportOpenResult` distinguishes:

```text
OPENED     resource_released = false
CANCELLED  resource_released = true, with the cooperative-cancellation stage
```

### 3.2 FrameReader and BootProtocolClient

`FrameReader` preserves raw-byte magic synchronization, dirty-byte discard,
partial buffering, odd-byte handling, header/payload validation, CRC checking,
and frame decoding.

`BootProtocolClient.transact()` is the only protocol transaction entry. One
complete request write and response read is protected by the client transaction
lock. Command timeout selection comes from the command-timeout table.

The client owns the connected session's cached `DeviceInfo`,
`ProtocolInfo`, and negotiated effective limits:

```text
effective_max_payload_words
effective_max_data_words
effective_max_write_data_words
```

Persistent discovery requires both `GET_DEVICE_INFO` and
`GET_PROTOCOL_INFO`. `discover_connected_target()` validates both and
returns the active `TargetProfile`; `GET_DEVICE_INFO` alone is insufficient
before non-bootstrap operations.

### 3.3 UpgradeSession

`UpgradeSession` owns one transport and one `BootProtocolClient`.
`connect(cancellation=None)` opens the transport and returns its typed open
result; `disconnect()` closes it. Session does not expose Flash, metadata,
RUN, confirmation, or workflow methods.

## 4. Target and image contracts

### 4.1 TargetProfile dispatch

`CommandSet` contains optional command bindings. `require_command()` rejects
an unavailable operation rather than substituting a command from another
Target. `TargetProfile.memory_map` supplies Flash, RAM, metadata, forbidden
sector, and service-region facts.

CPU-specific information is allowed in Profile construction and memory-layout
data. It is not allowed as duplicated shared operation sequencing.

### 4.2 Prepared images

```python
ImageIdentity(entry_point, image_size_words, image_crc32, app_end)
PreparedFlashImage(image, identity, sector_mask, generated_sci8_txt)
PreparedRamImage(image, entry_point, total_words, image_crc32, generated_sci8_txt)
PreparedServiceImage(
    image,
    descriptor_address,
    api_table_address,
    crc_patch_address,
    total_words,
    expected_crc32,
    required_capabilities,
)
```

`prepare_flash_app_image()` validates Flash ranges, entry point, metadata
exclusion, sector mask, and forbidden sectors using the active Profile.
`prepare_ram_app_image()` validates RAM load/execution ranges, reserved
regions, service conflicts, and CRC.

Image/metadata identity comparison uses entry point, image size, and image CRC.
It does not compare `app_end` because the current metadata-summary payload does
not expose that field.

### 4.3 Shared Flash-service resource

`AppResourceProvider` supplies one shared service source artifact. It is not a
CPU1-owned or CPU2-owned GUI setting.

For each operation materialization, `prepare_service_image()` resolves and
patches the artifact against the active `TargetProfile`, validates RAM ranges,
descriptor and symbols, calculates the formal CRC, and carries required ABI and
capability expectations in `PreparedServiceImage`. Materialized service state
is used for the current operation and is not converted into per-CPU editable
GUI paths.

## 5. Context, result, and progress

```python
OperationContext(
    session: UpgradeSession,
    target: TargetProfile,
    progress: ProgressCallback | None,
    cancellation: CancellationToken | None,
)

FlashOperationContext(
    ...,
    service: PreparedServiceImage,
    force_service_attach: bool = False,
)
```

Image inputs belong to immutable request objects, not Context. RAM operations
use `OperationContext`; operations requiring the downloaded Flash service use
`FlashOperationContext`. Normal Flash and metadata service-dependent operations
continue to call `ensure_service_attached()` internally, so callers do not need
to attach the service first. The operation library also provides
`get_service_status(ctx)` and `attach_flash_service(ctx)` for advanced
diagnostics, bring-up, and future advanced CLI use. GUI does not need to add a
direct Service Attach control.

Every public operation returns `OperationResult`. Its stable fields are:

```text
ok, operation, target, stage
summary, details, service, warning
error: OperationErrorInfo | None
completion: SUCCEEDED | FAILED | CANCELLED | COMPLETED_AFTER_CANCEL_REQUEST
cancellation: OperationCancellationInfo | None
```

`summary` is caller-facing output; `details` is diagnostic detail;
`service` reports internal attach/reuse; known transport, protocol, DSP-status,
service, safety, and unsupported-operation failures return typed error
information. Unknown programming errors are not silently converted.

### 5.1 Error domains

Every failed `OperationResult` carries an `OperationErrorInfo` whose
`domain` is one of:

```text
OPERATION       local validation, capability, sequencing, safety, or DSP business status
COMMUNICATION   transport failure, frame/protocol decoding failure, or wire-integrity status
```

The shared exception classifier is deliberately narrow:

- `OperationFailure`, `UnsupportedOperationError`, and
  `ProtocolPayloadLimitError` are `OPERATION` failures.
- `ProtocolDecodeError` and `TransportError` are `COMMUNICATION` failures.
- `ProtocolStatusError` is `COMMUNICATION` only for `BAD_PAYLOAD_CRC`,
  `UNSUPPORTED_PROTOCOL`, `BAD_PACKET_TYPE`, and `BAD_FLAGS`; every other
  DSP status, including `BAD_PAYLOAD_LENGTH` and unknown status values, is an
  `OPERATION` failure.
- An exception outside this classification is an unknown programming error
  and propagates to its caller.

`ProtocolPayloadLimitError` is a local pre-send `ProtocolClientError`. It is
reported as `PAYLOAD_LIMIT_EXCEEDED` with the command and effective/device/
protocol payload limits in `OperationErrorInfo.details`; it is not a frame or
transport failure. This classification changes no wire behavior.

`GuiRuntimeError.domain` may carry the operation result domain. The domain is
independent of `ErrorDisposition`: disconnect prompts remain governed by the
existing outcome-uncertainty and error-code rules.

`ProgressEvent` reports operation, Target, stage, message, word counts, chunk
size, details, and whether the just-completed boundary supports cooperative
cancellation. RAM/service load, Program, and Verify data transfers report
progress after accepted chunks.

## 6. Downloaded service runtime

`ensure_service_attached()` is internal to service-dependent operations:

```text
GET_SERVICE_STATUS
  -> reuse only if state, ABI, CRC, word count, and capabilities match
  -> otherwise invalidate descriptor magic
  -> RAM_LOAD formal service image
  -> RAM_CHECK_CRC
  -> SERVICE_ATTACH
  -> GET_SERVICE_STATUS and validate
```

Capability validation uses `ctx.service.required_capabilities`; it is not
guessed from the map file.

### Descriptor-last and CRC

The following ordering is mandatory:

1. Pre-invalidate descriptor magic.
2. Send all non-descriptor words first.
3. Send descriptor/header words last.
4. Calculate CRC in formal service receive order.
5. Exclude the invalidation transaction from the formal image CRC.
6. Use the same formal service CRC for `RAM_CHECK_CRC` and
   `SERVICE_ATTACH`.

The invalidation is a separate safety transaction. Address-order CRC must not
replace descriptor-last receive-order CRC.

## 7. Public atomic operations

### 7.1 Read-only status and explicit service operations

```python
get_device_info(ctx)
get_protocol_info(ctx)
get_last_error(ctx)
get_metadata_summary(ctx)
get_service_status(ctx)
attach_flash_service(ctx)
```

`get_metadata_summary()` is a bootloader-resident read and does not require
the Flash service. `get_service_status()` is a read-only `GET_SERVICE_STATUS`
operation; it does not ensure, load, validate, or attach a service. Status
operations do not mutate metadata.

`attach_flash_service()` ensures that the requested `PreparedServiceImage` is
attached and validated by using the existing internal service runtime. It does
not create a second service-loader sequence. The existing descriptor-last,
CRC, ABI, and capability rules remain unchanged.

### 7.2 Flash operations

```python
erase_flash_image_area(ctx, EraseFlashImageAreaRequest(image))
erase_sector_mask(ctx, EraseSectorMaskRequest(sector_mask))
program_flash_image(ctx, ProgramFlashImageRequest(image))
verify_flash_image(ctx, VerifyFlashImageRequest(image))
```

All use the active Profile and ensure the service internally.

- `erase_flash_image_area()` erases the metadata-sharing sector first, then
  remaining required application sectors; it does not Program, Verify, or write
  metadata.
- `erase_sector_mask()` validates the explicit mask and forbidden sectors.
- `program_flash_image()` performs PROGRAM BEGIN/DATA/END only; it does not
  Erase, Verify, or append IMAGE_VALID.
- `verify_flash_image()` performs VERIFY BEGIN/DATA/END only; it does not
  append IMAGE_VALID.

### 7.3 Metadata operations

```python
append_image_valid(ctx, AppendImageValidRequest(image))
append_boot_attempt(ctx, AppendBootAttemptRequest())
append_app_confirmed(ctx, AppendAppConfirmedRequest())
```

Each operation ensures the service, reads current metadata as needed, writes at
most its named record, and never runs the application or writes another record.

- IMAGE_VALID is appended only from an EMPTY metadata lifecycle; an existing
  valid image is an idempotent business result, while invalid metadata is
  reported without writing.
- BOOT_ATTEMPT requires the current IMAGE_VALID, valid attempt limit, and an
  unconfirmed image. It appends one attempt until the limit, capped at three.
- APP_CONFIRMED requires the current IMAGE_VALID and at least one current
  BOOT_ATTEMPT; an existing confirmation is idempotent.

The lifecycle order is:

```text
IMAGE_VALID -> BOOT_ATTEMPT -> APP_CONFIRMED
```

Metadata business states such as already-exists, prerequisite-required,
attempt-limit-reached, identity mismatch, and metadata-invalid are reported in
`OperationResult.summary`; they are not transport failures.

### 7.4 RAM operations

```python
load_ram_image(ctx, LoadRamImageRequest(image))
check_ram_crc(ctx, CheckRamCrcRequest(image))
```

`load_ram_image()` performs RAM_LOAD BEGIN/DATA/END and does not RUN_RAM.
`check_ram_crc()` performs RAM_CHECK_CRC and does not load or execute.

### 7.5 Execution operations

The formal public execution operations are:

```python
run_flash_app(ctx, RunFlashAppRequest(entry_point))
run_ram_image(ctx, RunRamImageRequest(entry_point))
reset_target(ctx, ResetTargetRequest())
```

`run_flash_app()`:

- obtains RUN from `ctx.target.command_set`;
- sends only the existing Flash App RUN;
- does not write BOOT_ATTEMPT or APP_CONFIRMED;
- does not refresh metadata;
- does not attach the service;
- does not reparse Program Image;
- does not select a second flow by CPU name.

`run_ram_image()` sends RUN_RAM only. It does not RAM Load or RAM CRC and is a
different atomic operation from Flash RUN.

`reset_target()` sends RESET only. Admission depends on the active
`TargetProfile`, advertised DeviceInfo capability, and Runtime gate. This
contract does not claim that production Reset is currently enabled.

## 8. Explicit Flash RUN and normal Program workflow

PC explicit Flash RUN requires valid metadata, a valid current IMAGE_VALID, and a valid entry point. It does not require:

```text
BOOT_ATTEMPT
APP_CONFIRMED
current Program Image
VerifyEvidence
```

A normal Program workflow may independently append BOOT_ATTEMPT and then call
the same `run_flash_app()`. It must not introduce a second RUN operation, a
mode flag, or a hidden capability gate. The operation library preserves atomic
RUN semantics and does not own GUI admission truth.

Automatic boot remains a separate DSP/metadata policy defined by [`dsp_bootloader.md`](dsp_bootloader.md) and [`metadata_journal.md`](metadata_journal.md).

## 9. Cancellation and recovery

`CancellationToken` is read-only to transport, session, protocol, and
operations; the caller owns the mutable cancellation source. An active protocol
transaction is never interrupted. Cancellation is observed only at defined safe
boundaries.

For RAM, service, Program, and Verify transfers:

- cancellation after a DATA transaction uses the next safe boundary;
- partial transfer cleanup sends the matching END exactly once with original
  packet and word totals;
- `TOTAL_COUNT_MISMATCH` from a partial cleanup END means the DSP discarded
  the partial session and is accepted as clean cleanup;
- other cleanup failures mark the outcome uncertain and require reconnect;
- cancellation after successful completion is reported as
  `COMPLETED_AFTER_CANCEL_REQUEST`.

If Program DATA was accepted, retry requires Erase first. The result records
`partial_flash_programmed`, `erase_before_retry_required`, protocol-clean
state, uncertainty, reconnect requirement, and a caller recovery action.
Recovery actions are instructions only: the operation library does not
automatically erase, retry, reconnect, or restart.

GUI persistent Connect passes the same read-only token through transport open
and atomic target discovery. It does not start discovery after an open-stage
cancellation and does not double-close a resource already released by the
transport. Cleanup failure is reported without advertising a connected state.

## 10. Integration boundary

User-maintained low-level DSP initialization, raw F021 integration, service artifact generation, and linker placement remain outside the PC operation library and are described by the [porting guide](../guides/f28377d_porting.md). CPU2 and W5300/TCP operations remain unavailable until their target profiles, commands, resources, firmware, and capabilities exist; shared code must not route them through CPU1 defaults.
