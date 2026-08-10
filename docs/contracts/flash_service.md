# Downloaded Flash Service Contract

## Partition and ownership

The product consists of a small Flash-resident bootloader core and a separately linked service downloaded to RAM. The core owns connection, protocol framing/dispatch, RAM-load primitives, service management, and action return. It must not statically link F021 or `flash_service_lib` and must not contain Erase, Program, Verify, or metadata-write implementations.

The downloaded service owns Flash erase/program/verify sessions, raw-Flash wrapper calls, buffering, Flash diagnostic mapping, command-payload validation after dispatch, and controlled metadata appends. The bootloader reads metadata; all Flash and metadata writes go through this service.

Host tests may link both parts for testing, but the product Flash image must not contain the service binary. User-owned artifact construction, device initialization, F021 integration, and linker placement remain governed by the [porting guide](../guides/f28377d_porting.md).

## Artifact lifecycle

For an operation that needs the service, the PC operation library obtains the service artifact from its resource provider, materializes it for the active target profile, validates its RAM ranges and descriptor metadata, loads it with RAM_LOAD commands, verifies its RAM CRC, and invokes `SERVICE_ATTACH`. The operation library owns this internal sequence; the GUI does not expose attach as an action.

The PC resolves the descriptor address from the service linker map or symbol and supplies that address in `SERVICE_ATTACH`. The bootloader never hard-codes a descriptor address derived from a PC artifact.

## Descriptor and header

The immutable descriptor/header is published last in the service image. `BootFlashServiceHeader` describes at least the service identity, header size/version, ABI major/minor, immutable image range and CRC, mutable ranges, entry functions, and advertised capabilities. Fields and code addresses use C28x 16-bit word addressing and must fall within the generated target RAM regions.

Before attachment, the core validates:

- descriptor magic, version, size, and header CRC;
- supported ABI compatibility;
- immutable image address range and CRC;
- executable entry addresses and RAM boundaries;
- mutable/stack regions and non-overlap constraints;
- required service capabilities.

An erased, partial, corrupt, unpublished, out-of-range, incompatible, or under-capable descriptor is rejected. Attachment does not execute a Flash command.

## ABI

The stable ABI uses `BOOT_FLASH_SERVICE_ABI_MAJOR = 2` and two core-facing function classes:

```text
BootFlashServiceBootInitFn       -> boot_init
BootFlashServiceHandleCommandFn  -> boot_handle_command
```

`boot_init` establishes service state and validates any ABI-level inputs. `boot_handle_command` receives only service-owned commands already accepted by the core dispatcher and returns a protocol-compatible result plus detailed error information. ABI evolution must preserve major-version compatibility rules and cannot silently reinterpret existing fields or capabilities.

The service reuses shared protocol/common definitions but does not copy the core receive loop, frame encoder/decoder, response sender, IO implementation, or top-level dispatcher.

## Service state and commands

Service state is limited to the active Program or Verify transaction, current target/range, expected blocks and words, next block index, received counts, and last detailed error. It does not keep a full Flash-write history.

ProgramData and VerifyData remain eight-word aligned. Program uses PC-provided `0xFFFF` padding and must not reprogram an AutoECC unit before erase. Any Program or Verify failure terminates that session. Detailed F021/API/FMSTAT failures are preserved for conversion to the protocol ErrorDetail; they are not collapsed into a boolean or exposed as a new generic status.

The service performs controlled journal appends, including IMAGE_VALID, BOOT_ATTEMPT, and APP_CONFIRMED, according to [metadata_journal.md](metadata_journal.md). It does not redefine record layout or binding semantics.

Wire command IDs, payloads, status codes, and SERVICE_ATTACH serialization remain authoritative in [communication_protocol.md](communication_protocol.md). Public PC sequencing and admission remain authoritative in [pc_operations.md](pc_operations.md).

## RAM writable limits

`bootloader_autogen/boot_user_ram_limit.h` is generated before the CPU1 CCS project is imported or built and is intentionally untracked. The generator combines linker MEMORY and map allocations, requires bootloader-owned RAM to be one continuous edge-anchored RAMGS interval, and removes BOOT_RSVD, RAMM1, RESET, errata tails, and that bootloader interval from candidate RAM_LOAD regions. BEGIN is writable only when present in the generated table. Range ends are exclusive C28x word addresses.
