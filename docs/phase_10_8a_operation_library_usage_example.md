# Phase 10.8A PC Operation Library Usage Example

> Project: `bootloader_upgrade_tool`  
> Target: TMS320F28377D CPU1  
> Purpose: shared usage guide for Phase 11 GUI / PC workflow integration  
> Scope: PC-side usage examples only. No DSP code, no linker changes, no hardware initialization changes.

---

## 1. Purpose

Phase 10.8A introduced a new PC-side library split:

```text
transport/
protocol/
session/
targets/
images/
operations/
```

The purpose is to let the future PySide6 GUI use a persistent session and operation layer instead of repeatedly launching the old `cpu1_upgrade` CLI.

The old CLI and `UpgradeWorkflow` remain useful as validated references and regression targets, but Phase 11 GUI should not be implemented as:

```text
GUI button -> subprocess -> cpu1_upgrade CLI command
```

The intended model is:

```text
GUI / ViewModel / Controller
    -> operations/*
        -> UpgradeSession.client.transact(command_id, payload)
            -> BootProtocolClient
                -> FrameReader
                    -> ByteTransport
```

---

## 2. Basic persistent session example

```python
from threading import Event

from bootloader_upgrade_tool.session import UpgradeSession, UpgradeSessionConfig
from bootloader_upgrade_tool.operations import discover_connected_target
from bootloader_upgrade_tool.transport.serial_transport import SerialTransport, SerialTransportConfig
from bootloader_upgrade_tool.transport import TransportOpenStatus


class CancellationSource:
    def __init__(self) -> None:
        self._event = Event()

    def request_cancel(self) -> None:
        self._event.set()

    def is_cancel_requested(self) -> bool:
        return self._event.is_set()


cancellation = CancellationSource()
transport = SerialTransport(
    SerialTransportConfig(
        port="COM3",
        baudrate=9600,
        tx_timeout_ms=1000,
        rx_timeout_ms=1000,
        autobaud_timeout_ms=5000,
    )
)

session = UpgradeSession(UpgradeSessionConfig(transport))
open_result = session.connect(cancellation)
if open_result.status is TransportOpenStatus.CANCELLED:
    print(f"Connection cancelled during {open_result.stage}")
    raise SystemExit(0)

discovery = discover_connected_target(session)
if not discovery.result.ok:
    try:
        session.disconnect()
    finally:
        print("Target discovery failed", discovery.result.error)
    raise SystemExit(1)

target = discovery.discovered_target.target_profile
```

The caller owns `request_cancel()`; the session and operation library receive
only the read-only `is_cancel_requested()` contract.
`TransportOpenStatus.OPENED` does not yet make the session ready for persistent
operations. Discovery must succeed before the session is retained, and a
discovery failure releases the session/transport. Cleanup can itself fail and
is not retried automatically by this example.

`discover_connected_target()` performs both `GET_DEVICE_INFO` and
`GET_PROTOCOL_INFO`. Both must succeed before Program, Verify, RAM load,
service attach, metadata, Run, or Reset operations begin. `get_device_info()`
alone is not complete capability discovery. Subsequent GUI operations reuse
the same session and the discovered `target` profile.

---

## 3. Preparing images

```python
from bootloader_upgrade_tool.images import (
    prepare_flash_app_image,
    prepare_ram_app_image,
    prepare_service_image,
)
from bootloader_upgrade_tool.targets import CPU1_PROFILE

app = prepare_flash_app_image(
    app_image_path="build/app_cpu1.out",
    target=CPU1_PROFILE,
    hex2000="C:/ti/ccs/tools/compiler/ti-cgt-c2000/bin/hex2000.exe",
)

ram_app = prepare_ram_app_image(
    ram_image_path="build/ram_app_cpu1.out",
    target=CPU1_PROFILE,
    hex2000="C:/ti/ccs/tools/compiler/ti-cgt-c2000/bin/hex2000.exe",
)

service = prepare_service_image(
    service_image_path="build/flash_service_lib_cpu1.out",
    service_map_path="build/flash_service_lib_cpu1.map",
    target=CPU1_PROFILE,
)
```

The descriptor address is parsed from map/symbol data. Do not hardcode it in the GUI or bootloader.

---

## 4. Flash operation context

```python
from bootloader_upgrade_tool.operations import FlashOperationContext, OperationContext

def progress_callback(event):
    print(event.operation, event.stage, event.current_words, event.total_words)

ctx = OperationContext(
    session=session,
    target=target,
    progress=progress_callback,
    cancellation=cancellation,
)

flash_ctx = FlashOperationContext(
    session=session,
    target=target,
    progress=progress_callback,
    cancellation=cancellation,
    service=service,
    force_service_attach=False,
)
```

`SERVICE_ATTACH` is internal. GUI should not expose it as a normal workflow button.
The caller owns the mutable cancellation source. The session and operation
library receive only its read-only `is_cancel_requested()` contract and never
request cancellation themselves.

For DATA progress events, `ProgressEvent.cancellation_supported=True` means
the previous DATA transaction is complete and the event marks a safe
cooperative cancellation boundary. It is not permission to interrupt the
active protocol transaction.

---

## 5. Flash App sequence

```python
from bootloader_upgrade_tool.operations import (
    EraseFlashImageAreaRequest,
    ProgramFlashImageRequest,
    VerifyFlashImageRequest,
    AppendImageValidRequest,
    erase_flash_image_area,
    program_flash_image,
    verify_flash_image,
    append_image_valid,
)

steps = [
    (erase_flash_image_area, EraseFlashImageAreaRequest(app)),
    (program_flash_image, ProgramFlashImageRequest(app)),
    (verify_flash_image, VerifyFlashImageRequest(app)),
    (append_image_valid, AppendImageValidRequest(app)),
]

for operation, request in steps:
    result = operation(flash_ctx, request)
    if not result.ok:
        print("FAILED", result.operation, result.stage, result.error)
        break
    print("OK", result.operation, result.summary)
```

Important:

```text
verify_flash_image() does not write IMAGE_VALID.
append_image_valid() writes IMAGE_VALID separately.
```

---

## 6. Run App sequence

```python
from bootloader_upgrade_tool.operations import (
    AppendBootAttemptRequest,
    RunFlashAppRequest,
    append_boot_attempt,
    run_flash_app,
)

result = append_boot_attempt(
    flash_ctx,
    AppendBootAttemptRequest(app.identity),
)

if result.ok:
    result = run_flash_app(
        ctx,
        RunFlashAppRequest(entry_point=app.identity.entry_point),
    )
```

Important:

```text
run_flash_app() only sends RUN.
run_flash_app() does not write BOOT_ATTEMPT.
append_boot_attempt() writes BOOT_ATTEMPT separately.
```

---

## 7. Confirm App sequence

```python
from bootloader_upgrade_tool.operations import (
    AppendAppConfirmedRequest,
    append_app_confirmed,
)

result = append_app_confirmed(
    flash_ctx,
    AppendAppConfirmedRequest(app.identity),
)
```

Rules:

```text
append_app_confirmed() requires matching IMAGE_VALID.
append_app_confirmed() requires existing BOOT_ATTEMPT.
APP_CONFIRMED must bind to the current IMAGE_VALID.
```

---

## 8. RAM App sequence

```python
from bootloader_upgrade_tool.operations import (
    CheckRamCrcRequest,
    LoadRamImageRequest,
    RunRamImageRequest,
    check_ram_crc,
    load_ram_image,
    run_ram_image,
)

result = load_ram_image(ctx, LoadRamImageRequest(ram_app))
if result.ok:
    result = check_ram_crc(ctx, CheckRamCrcRequest(ram_app))
if result.ok:
    result = run_ram_image(ctx, RunRamImageRequest(ram_app))
```

Important:

```text
load_ram_image() does not RUN_RAM.
check_ram_crc() only sends RAM_CHECK_CRC.
run_ram_image() does not load RAM image.
run_ram_image() does not check RAM CRC.
```

---

## 9. OperationResult handling

```python
from bootloader_upgrade_tool.operations import OperationCompletion, operation_result_to_dict

result_dict = operation_result_to_dict(result)

if result.completion is OperationCompletion.SUCCEEDED:
    continue_workflow(result)
elif result.completion is OperationCompletion.FAILED:
    show_error(
        code=result.error.code,
        message=result.error.message,
        stage=result.error.stage,
        details=result.error.details,
    )
elif result.completion is OperationCompletion.CANCELLED:
    stop_workflow(result.cancellation.recovery_action)
elif result.completion is OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST:
    show_success(result.operation, result.summary)
    stop_before_next_operation()
```

`CANCELLED` is a normal cancellation outcome; do not read `result.error` for
it. Inspect `result.cancellation.recovery_action` instead.
`COMPLETED_AFTER_CANCEL_REQUEST` means the current operation completed
successfully, but cancellation remains requested, so do not start the next
operation.

Recovery actions include:

```text
RESTART_RAM_LOAD
RESTART_SERVICE_LOAD
RESTART_PROGRAM
ERASE_AND_RESTART_PROGRAM
RESTART_VERIFY
RECONNECT_AND_RESTART_*
RECONNECT_ERASE_AND_RESTART_PROGRAM
```

These are caller instructions. The library does not automatically reconnect,
erase, restart, or retry.

Business-state examples may return `ok=True`:

```text
IMAGE_VALID_ALREADY_EXISTS
BOOT_ATTEMPT_ALREADY_EXISTS
APP_CONFIRMED_ALREADY_EXISTS
IMAGE_VALID_REQUIRED
BOOT_ATTEMPT_REQUIRED
```

GUI should show these as workflow guidance rather than fatal protocol errors.

---

## 10. Testing pattern

GUI tests should not open real serial ports or touch hardware.

A fake client can enforce operation-layer discipline:

```python
class FakeClient:
    def __init__(self):
        self.device_info = fake_device_info()
        self.calls = []
        self.responses = {}

    def transact(self, command: int, payload=(), *, timeout_ms=None):
        assert type(command) is int
        self.calls.append((command, tuple(payload)))
        queue = self.responses.get(command)
        return queue.pop(0) if queue else ()

    def __getattr__(self, name: str):
        raise AssertionError(f"operation used protocol convenience method: {name}")
```

This catches accidental direct calls like:

```text
client.program_begin()
client.metadata_append_image_valid()
client.service_attach()
```

---

## 11. Codex safety boundary

Codex must not execute real hardware actions:

```text
open a real COM port
perform real autobaud
erase real Flash
program real Flash
verify real Flash
write real metadata
reset DSP
observe LED behavior
```

For hardware validation, Codex must stop and hand control back to the user.
