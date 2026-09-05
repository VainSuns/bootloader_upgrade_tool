# CLI V1 Contract

## 1. Authority and scope

This document is the long-term authority for the formal CLI product surface:

```text
entry points
parser command tree
CLI options
one-shot lifecycle
confirmation
progress presentation
stdout/stderr behavior
JSON envelopes
exit codes
interactive shell behavior
CLI-specific connection release
```

It is a presentation and lifecycle contract. It does not become a second copy
of another domain contract. The following authorities remain outside this
document:

| Subject | Authority |
|---|---|
| wire format, protocol command IDs, payloads, and statuses | [Communication protocol](communication_protocol.md) |
| operation admission, sequencing, cancellation, and atomic results | [PC operations](pc_operations.md) |
| TargetProfile and memory-map facts | [PC operations](pc_operations.md) |
| Flash Service ABI and artifact rules | [Flash Service](flash_service.md) |
| metadata binary layout, binding, scanning, and publication | [Metadata journal](metadata_journal.md) |
| DSP automatic-boot policy | [DSP bootloader](dsp_bootloader.md) and [Metadata journal](metadata_journal.md) |
| GUI Runtime ownership and GUI dependency direction | [Runtime architecture](runtime_architecture.md) |

The CLI does not change these contracts or expose their internal state
machines directly.

## 2. Entry points

The formal CLI is available as:

```text
bootloader-cli
python -m bootloader_upgrade_tool.cli
```

`python -m bootloader_upgrade_tool` remains the PySide6 GUI entry point. The
CLI does not replace, reroute, or invoke the GUI entry point.

## 3. Global and session options

The current parser exposes these global/session options:

| Option | Current contract |
|---|---|
| `--transport` | transport provider; default `serial`, and currently only `serial` is supported |
| `--port` | serial endpoint; required for command execution |
| `--baud` | positive serial baud rate; default `9600` |
| `--timeout-ms` | positive override for serial TX, RX, and autobaud timeouts only |
| `--json` | render final outcomes as JSON |
| `--verbose` | include verbose diagnostics |
| `--version` | print the CLI distribution version and exit |

`--timeout-ms` does not override formal protocol command timeouts. SCI `A`
autobaud remains SerialTransport/connection-layer behavior, not a protocol
frame. `--version` and help are parser actions and do not require a port.

Service-dependent one-shot commands take the paired options
`--flash-service-image` and `--flash-service-map`. The pair is required
together; a descriptor address is not a CLI input. Flash Service materialization
and descriptor resolution follow [PC operations](pc_operations.md) and the
[Flash Service](flash_service.md) contract.

Command-specific inputs are:

```text
erase                  exactly one of --image, --all-app, --sector-mask
program                --image
verify                 --image
metadata image-valid   --image
ram load               --image
ram check-crc          --image
memory read            --address and --words
run-ram                --entry-point
upgrade                --image and optional --no-run
```

The service-dependent commands in that list, and `metadata boot-attempt`,
`metadata app-confirmed`, and `service attach`, also require the paired Flash
Service source options. `--yes` is command-scoped and is documented in
[Confirmation](#9-confirmation).

## 4. Formal one-shot command tree

The one-shot parser exposes exactly this command tree:

```text
status
device-info
protocol-info
last-error

erase
program
verify

metadata
    status
    image-valid
    boot-attempt
    app-confirmed

service
    status
    attach

ram
    load
    check-crc

memory
    read

run
run-ram
upgrade

shell
```

`reset` is not exposed in CLI V1. `ping` is not a one-shot CLI command; it is
shell-only. A retained lower-layer `reset_target()` operation does not create
a CLI capability.

## 5. One-shot lifecycle

Each one-shot command follows:

```text
connection configuration
→ connect/autobaud
→ target discovery
→ execute command
→ disconnect
```

Discovery establishes the active target from the connected session before
non-bootstrap command execution. A connection or discovery failure is cleaned
up and reported as the final one-shot outcome. Cancellation is cooperative
through the current connection generation. CLI usage/configuration failures
are reported before execution, and unexpected programming failures are
reported as internal errors according to the exit-code contract.

The CLI does not add automatic retry, reconnect, recovery, or resume behavior.
Operation and business semantics remain defined by [PC operations](pc_operations.md).

## 6. Command semantics as presented by the CLI

### 6.1 Read-only commands

The read-only CLI commands are:

```text
status
device-info
protocol-info
last-error
metadata status
service status
memory read
```

`status` presents the discovered target and a current metadata summary.
`device-info` and `protocol-info` present the typed information cached during
discovery. `last-error` reads the bootloader's last operation error only when
the user explicitly invokes `last-error`; it is not a hidden recovery step.
`metadata status` is a metadata read, and `service status` is a read-only
service-status read that does not load or attach a service.

`memory read` uses a C28x 16-bit word address, not a byte address. Its memory
semantics remain those of the active target and [Communication protocol](communication_protocol.md).

### 6.2 Flash and service commands

```text
erase
program
verify
service attach
```

These are atomic public-operation presentations. `program` means Program only;
it does not Erase, Verify, or publish IMAGE_VALID. `verify` means Verify only;
it does not publish IMAGE_VALID. `service attach` ensures the requested Flash
Service is attached; the CLI does not take a descriptor address directly.

The Flash Service source pair is supplied by
`--flash-service-image` and `--flash-service-map`. The actual materialization,
attachment, and Flash rules are defined by [PC operations](pc_operations.md)
and [Flash Service](flash_service.md).

### 6.3 Metadata commands

```text
metadata image-valid
metadata boot-attempt
metadata app-confirmed
```

The CLI-visible distinctions are:

```text
image-valid
    publishes IMAGE_VALID only
    does not Verify

boot-attempt
    writes BOOT_ATTEMPT only
    does not RUN

app-confirmed
    is an engineering override
    bypasses the normal App self-confirmation path
```

Operation-layer prerequisites and the metadata lifecycle remain authoritative
in [PC operations](pc_operations.md) and [Metadata journal](metadata_journal.md).

### 6.4 RAM commands

```text
ram load
ram check-crc
run-ram
```

Their atomic semantics are:

```text
ram load       = RAM load only
ram check-crc  = CRC check only
run-ram        = RUN_RAM only
```

`run-ram` does not load RAM or perform RAM_CHECK_CRC and does not require
CLI-local, connection-local RAM-load/CRC evidence. It remains subject to the
active target's command and RAM admission and the DSP's own RUN_RAM rules.

## 7. Explicit Flash RUN

`run` presents this flow:

```text
read current metadata
→ require valid current IMAGE_VALID and entry point
→ confirmation
→ explicit RUN
```

The CLI requires a valid current published image, a valid entry point, matching
discovered target identity, and an entry point admitted by the active Flash
profile. Explicit RUN does not require:

```text
BOOT_ATTEMPT
APP_CONFIRMED
confirmed_bootable
VerifyEvidence
--image
Flash Service
```

Explicit RUN does not write BOOT_ATTEMPT. Automatic boot is a different policy;
its `confirmed_bootable` rule is defined by [DSP bootloader](dsp_bootloader.md)
and [Metadata journal](metadata_journal.md).

## 8. Standard upgrade workflow

`upgrade` uses the fixed standard sequence:

```text
ERASE
→ PROGRAM
→ VERIFY
→ IMAGE_VALID
→ final cancellation gate
→ BOOT_ATTEMPT
→ RUN
```

`upgrade --no-run` uses:

```text
ERASE
→ PROGRAM
→ VERIFY
→ IMAGE_VALID
→ STOP
```

Therefore:

```text
--no-run:
    BOOT_ATTEMPT = 0
    RUN = 0

normal upgrade:
    APP_CONFIRMED = 0
```

Here `0` means that the workflow does not append that record for the current
image. A new IMAGE_VALID starts a new metadata lifecycle; the workflow never
appends APP_CONFIRMED.

Only `OperationCompletion.SUCCEEDED` permits the next workflow stage. In the
normal upgrade, `BOOT_ATTEMPT → RUN` is the non-cancellable commit-to-run tail.
The CLI performs no automatic retry, reconnect, GET_LAST_ERROR recovery, PING
recovery, or resume. Detailed cancellation and operation-result rules remain
in [PC operations](pc_operations.md).

## 9. Confirmation

Confirmation is required for:

```text
erase
program
metadata image-valid
metadata boot-attempt
metadata app-confirmed
run
run-ram
upgrade
```

Confirmation is not required for:

```text
status
device-info
protocol-info
last-error
metadata status
verify
service status
service attach
ram load
ram check-crc
memory read
```

`--yes` is exactly the approved confirmation decision. It is not a general
safety bypass and does not skip preparation, admission, or operation checks.
In the interactive shell it is an option on an individual command, not a
session-global setting.

## 10. Progress

`ProgressEvent` is the operation-progress authority. The CLI renderer only
turns those events into presentation on stderr.

For `upgrade`, presentation contains the workflow stage index and name, plus
the current operation's own progress when available. The CLI does not invent
an overall workflow percentage. Progress, warnings, prompts, and transient
status remain separate from the final result stream.

## 11. Output, JSON, and exit codes

The stream contract is:

```text
stdout = final result
stderr = progress / warning / prompt / transient status
```

For a one-shot invocation, `--json` emits one valid JSON document with
`schema_version: 1`. The envelope includes `command`, `success`, and the
numeric `exit_code`, plus a `result` or structured `error` when applicable.
The shell emits one such envelope per command outcome rather than combining
the session into one result object.

Exit codes are:

| Code | Meaning |
|---:|---|
| `0` | `SUCCESS` |
| `1` | `OPERATION_FAILURE` |
| `2` | `CLI_USAGE_ERROR` |
| `3` | `COMMUNICATION_FAILURE` |
| `4` | `CANCELLED` |
| `5` | `CONFIRMATION_REQUIRED` |
| `6` | `USER_DECLINED` |
| `7` | `INTERNAL_ERROR` |

`OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST` maps to the cancellation
exit category (`4`), even though the operation result itself is successful.

## 12. Interactive shell

Shell startup is:

```text
create shell
→ attempt connect
→ discover
→ prompt
```

An initial connection or discovery failure, including cooperative cancellation,
is reported while the shell remains alive. The shell-only commands are:

```text
connect
disconnect
reconnect
service use
ping
help
exit
quit
```

The target commands in the one-shot tree are also available at the shell
prompt. Shell connection and global presentation options are fixed at startup;
restart the shell to change them. Normal target commands use the one-shot
syntax without re-specifying those fixed options.

`exit`, `quit`, or EOF ends the shell with process exit code `0`. A target
command failure does not terminate the shell and does not become the final
shell process exit status.

## 13. Connection generations

Each new shell connection generation, including `connect` after a disconnect or
`reconnect`, has:

```text
fresh UpgradeSession
fresh target discovery
fresh cancellation source/token
fresh connection-bound state and materialization
```

Across disconnect/reconnect the shell retains:

```text
connection configuration
selected Flash Service source paths
presentation configuration
```

It does not retain:

```text
session
target
connection-bound materialization
prepared target-specific Service resource
```

An old generation's cancellation request cannot cancel or otherwise pollute a
new generation.

## 14. `service use`

The exact shell syntax is:

```text
service use --flash-service-image <path> --flash-service-map <path>
```

`service use` changes only the PC-local selected Flash Service image/map source
pair. The two paths are one pair: a well-formed replacement replaces both
atomically, while an invalid or incomplete replacement leaves the old pair
selected. It does not:

```text
connect DSP
RAM_LOAD
RAM_CHECK_CRC
SERVICE_ATTACH
```

## 15. Shell ping

`ping` is a shell-only diagnostic based on the public target-driven `ping(ctx)`
operation. It uses the active TargetProfile command admission and sends PING
only. It does not:

```text
GET_LAST_ERROR
retry
reconnect
automatic recovery
hidden health checks
```

It is not added to the one-shot parser. Operation facts are defined in
[PC operations](pc_operations.md).

## 16. Ctrl+C and cancellation

At the shell prompt:

```text
Ctrl+C
→ interrupt current input
→ shell stays alive
→ connection stays valid
→ cancellation token is not requested
→ prompt is redisplayed
```

During connect, discovery, or an active command, Ctrl+C requests cooperative
cancellation through the current generation's cancellation source. Safe
cancellation boundaries and result semantics are defined by [PC operations](pc_operations.md).

## 17. RUN/RUN_RAM shell connection release

For shell execution, a pre-wire RUN or RUN_RAM failure retains the connection.
The formal wire-attempt boundary is the point at which the operation has passed
local command/payload/frame validation and is immediately before the transport
write. Once an actual RUN or RUN_RAM wire attempt begins, the CLI releases the
bootloader connection and keeps the shell alive with a disconnected prompt.

For `upgrade`:

```text
--no-run
    remains connected

failure before final RUN
    does not trigger RUN-driven release

BOOT_ATTEMPT alone
    does not trigger release

actual final RUN attempt
    releases the connection
```

This section records the CLI lifecycle boundary only. The formal optional
observer and its exact transaction boundary are defined in [PC operations](pc_operations.md).

## 18. Architecture boundary

The dependency direction is:

```text
CLI
→ public operations / current CLI workflow composition
→ UpgradeSession
→ BootProtocolClient
→ ByteTransport
```

The CLI must not depend on:

```text
GUI
legacy cpu1_upgrade
core.UpgradeWorkflow
direct .transact() calls
direct protocol Command IDs
```

The shell does not own a second business workflow; it presents the same public
operations and current CLI workflow composition.

## 19. Deferred and unsupported CLI surface

The following are not part of CLI V1:

```text
reset
CPU2 CLI enablement
W5300/TCP transport
one-shot ping
```

Retained lower-layer capabilities must not be deleted merely because they are
not exposed by the CLI.
