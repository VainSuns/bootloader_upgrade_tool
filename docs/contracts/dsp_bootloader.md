# DSP Bootloader Contract

## Purpose and boundaries

The Flash-resident DSP bootloader is the communication and boot-decision core. It owns connection handling, framed-request dispatch, downloaded-service attachment, recovery timing, and returning device actions to the user port. It does not own raw TI initialization, F021 implementation, linker placement, application branch assembly, or device reset mechanics; those are described in the [porting guide](../guides/f28377d_porting.md).

The PC is master and the DSP is slave. The current CPU1 connection uses SCI-A on GPIO64/GPIO65 through RS232. SCI autobaud is connection-layer behavior: the PC sends ASCII `A` and the DSP echoes it before framed protocol traffic. It is not a protocol frame.

Wire frames, command payloads, status values, and error-detail encoding are defined only by the [communication protocol](communication_protocol.md).

## IO and user-port abstractions

The algorithm consumes a `BootIoOps`-style interface with context, blocking byte/word receive, and word send. The byte receive primitive has no protocol-timeout parameter. Autobaud and connection inactivity are controlled by the outer connection flow and do not invent a generic DSP timeout status.

Device registers are read only by the user port. A `BootUser_CreateDeviceInfo()`-style output interface supplies complete device identity and capability data to the core. DSP-facing function return values must not exceed 32 bits; larger information is returned through output pointers.

The core uses user-provided RAM validation/write primitives. Flash and metadata work is invoked only through the attached downloaded service described in [flash_service.md](flash_service.md).

## Main algorithm and state flow

The core performs this high-level flow:

1. Initialize the user port and scan metadata through its read-only boundary.
2. Evaluate `confirmed_bootable` using the current metadata relationship defined in [metadata_journal.md](metadata_journal.md).
3. If confirmed, allow a finite GUI takeover window; otherwise wait indefinitely for GUI autobaud.
4. Establish the protocol session and process valid master requests.
5. Handle core commands locally, RAM-load the service artifact, and attach it through the service ABI.
6. Dispatch Flash and metadata commands to the attached service under the execution guard.
7. Send the response before returning a RUN or RESET action to the user-owned outer loop.

Core state remains minimal: connection/protocol state, RAM-load state, attached-service state, last error, and a pending validated entry point. Flash program/verify session state belongs to the service.

### Last operation error

`last_error` is operation-level diagnostic state. It records the most recent
meaningful operation failure reported by a core command or the attached service.
Frame and protocol validation failures before command dispatch return their
defined protocol status only; they do not write, clear, or overwrite an existing
`last_error`.

## Device information boundary

Internal device identity may include PARTIDL, PARTIDH, REVID, UID_UNIQUE, UID_CHECKSUM, and UID_PSRAND values. Only fields defined by the current protocol version are exposed on the wire. Capabilities reflect the actual build; unavailable Reset, CPU2, or transport behavior is not advertised.

The current product build is CPU1 `FLASH_KERNEL` / `CORE_RAM_LIB` and supports the implemented Erase, Program, Verify, Run, Metadata, and Memory Read path. `RUN_RAM` remains available in the RAM development build. Capability statements do not authorize hard-coded CPU1 branching in shared PC runtime code.

## Data handling

ProgramData and VerifyData blocks contain a positive multiple of eight 16-bit words. The DSP rejects invalid Flash block counts with the protocol status defined for that condition. RamLoadData writes RAM and therefore accepts any positive word count whose payload and non-wrapping address range are valid and fully contained in a generated writable region.

A Flash Program or Verify failure ends the corresponding service session. The PC operation sequencing and retry/cancellation rules are authoritative in [pc_operations.md](pc_operations.md).

## RUN and RESET actions

The algorithm does not directly jump to an application or reset the device. For an accepted RUN or RESET request it first transmits the response, then returns a small action value to the user-owned outer loop. RUN stores the validated entry point for retrieval by the user port, which validates it again against the application range immediately before branching.

Automatic boot and explicit RUN are distinct. Automatic boot requires `confirmed_bootable`; explicit Flash RUN admission is defined by [pc_operations.md](pc_operations.md). Production RESET remains deferred and must not be advertised or enabled until its deterministic user-port action exists.

## Communication inactivity and recovery

CPU Timer2 provides the current 15000 ms communication-inactivity timeout. It starts only after GUI autobaud and protocol-session initialization. Therefore an unconfirmed application waits indefinitely before autobaud. Each request frame that passes frame, protocol-version, packet-type, flag, and CRC validation reloads Timer2 exactly once; noise and invalid frames do not.

Calls that execute Flash or metadata service commands use one outer critical guard:

```text
valid service command
-> save interrupt state and disable global interrupts
-> stop CPU Timer2
-> call service boot_handle_command()
-> reload and restart CPU Timer2
-> restore the prior interrupt state
```

`SERVICE_ATTACH` does not use this execution guard because it validates and connects a service without executing a Flash command. The service does not duplicate this Timer2 guard around individual F021 calls.

The Timer2 ISR performs only a forced device reset. It does not scan metadata, calculate `confirmed_bootable`, flush SCI, or jump to the application. After reset, startup scans fresh metadata and applies the normal boot policy. The optional PC Auto-PING maintenance architecture that prevents idle expiry is defined in [runtime_architecture.md](runtime_architecture.md).

## Automatic boot decision

`BootUser_IsConfirmedBootable()` is the single automatic-start decision authority at the DSP boundary. It requires valid metadata, a valid current IMAGE_VALID record, a BOOT_ATTEMPT bound to that image, APP_CONFIRMED bound to that image, and a valid entry point. Record layout, validity, scanning, and binding are defined only by [metadata_journal.md](metadata_journal.md).

The bootloader remains metadata-read-only. Application self-confirmation requests an APP_CONFIRMED append through the retained/downloaded Flash Service; the service owns the write.
