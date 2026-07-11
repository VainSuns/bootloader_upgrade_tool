# Phase 11.2 Batch 11 GUI Runtime Foundation — Agile Implementation Plan

## 1. Status

```text
Design approved by user: 2026-07-11
Baseline: 1f856ab5786ce3676897e8df560f0b885f9da4b1
Design branch: docs/phase11-2-batch11-runtime-design
Target: TMS320F28377D CPU1
```

This plan implements the approved Batch 11 architecture with an agile rule:

> Add only tests that protect critical runtime behavior. Do not create exhaustive tests for low-risk fields, trivial adapters, getters, labels, or every enum member.

The architecture and hardware boundaries in `phase_11_2_batch_11_runtime_foundation_design.md` remain unchanged. This plan supersedes only the earlier test granularity.

---

## 2. Scope

### Production files

```text
pc/src/bootloader_upgrade_tool/gui/runtime_models.py
pc/src/bootloader_upgrade_tool/gui/runtime_ports.py
pc/src/bootloader_upgrade_tool/gui/workers.py
pc/src/bootloader_upgrade_tool/gui/controller.py
pc/src/bootloader_upgrade_tool/gui/widgets/task_dialog.py
```

### Minimal test files

```text
tests/unit/gui_runtime_fakes.py
tests/unit/test_gui_runtime_core.py
tests/unit/test_gui_controller.py
tests/unit/test_gui_task_dialog.py
```

Existing file to update:

```text
tests/unit/test_gui_view_import_boundaries.py
```

### Explicitly excluded

```text
MainWindow / SessionRibbon runtime wiring
real RuntimeBackend
real serial connection and autobaud
UpgradeSession construction
operations/* execution
image preparation and cache implementation
Advanced page binding
Program workflow binding
Memory page binding
DSP / flash_lib / protocol / linker changes
CPU2 runtime
W5300 runtime
```

No implementation or test may open real hardware.

---

## 3. Testing policy

### Tests that are mandatory

Only the following risks justify new tests:

1. A Worker runs on the GUI thread or leaves a QThread alive.
2. Controller allows concurrent Tasks or performs an invalid runtime-state transition.
3. Cancellation or dialog closing destroys a running thread.
4. Worker result/thread completion ordering leaves a Task permanently busy.
5. Old-generation signals corrupt a later cleanup generation.
6. `ASK_DISCONNECT`, RUN/RESET-style release, or Shutdown enters the wrong connection state.
7. TaskDialog closes while work or mandatory disposition is active.
8. View imports backend/runtime implementation layers directly.
9. Any test accidentally reaches real serial, subprocess, Flash, metadata, RUN, RESET, CPU2, or W5300 code.

### Tests that shall not be added unless implementation reveals a defect

```text
every enum value independently
trivial dataclass getters
all invalid combinations of every field
all display labels and object names
all button enabled-state permutations
all equivalent admission rejection branches
adapter methods already exercised through Controller
full visual geometry matrix for TaskDialog
performance or stress tests
```

Use parameterized tests when several cases share one state-machine rule.

---

## 4. Task sequence

## Task 1 — Runtime models, Port contracts, and test fakes

### Files

Create:

```text
pc/src/bootloader_upgrade_tool/gui/runtime_models.py
pc/src/bootloader_upgrade_tool/gui/runtime_ports.py
tests/unit/gui_runtime_fakes.py
tests/unit/test_gui_runtime_core.py
```

### Implement

`runtime_models.py` shall contain the frozen enums and immutable public models from the approved design:

```text
RuntimeState
RuntimeSnapshot
ConnectionInfo
TaskPhase
TaskDispositionState
TaskFinalStatus
TaskStepState
ProgressMode
CompletionPolicy
TaskConnectionRequirement
TaskCompletionAction
TaskDialogAction
TaskStepPlan
TaskPlan
TaskProgressUpdate
TaskState
ErrorDisposition
GuiRuntimeError
GuiTaskWarning
TaskExecutionResult
RequestRejectionCode
RequestRejection
RequestAdmission
CancelRequestResult
TaskActionResult
ApplicationCloseDecision
ApplicationCloseResult
```

Required validation is limited to invariants that prevent invalid state-machine operation:

```text
TaskPlan has at least one Step
Step IDs are non-empty and unique
Step weights are positive
Task IDs match across Plan, State, Result, and error
CONNECTED requires ConnectionInfo
DISCONNECTED cannot retain ConnectionInfo
ERROR requires RUNTIME_FATAL last_error
FAILED requires error
CANCELLED and COMPLETED_AFTER_CANCEL_REQUEST require cancel_requested
ASK_DISCONNECT requires outcome_uncertain
RELEASE_CONNECTION is not valid for failed/local Tasks
```

GUI-owned `details` mappings must be defensively copied and recursively frozen. They must reject callbacks, QObject, session, transport, file handles, and arbitrary mutable runtime resources.

`runtime_ports.py` shall contain:

```text
GuiTaskRequest Protocol
ProgressCallback
CancellationToken
RuntimePort Protocol
TaskPort Protocol
WorkerJob Protocol
ConnectWorkerJob
DisconnectWorkerJob
ShutdownWorkerJob
TaskWorkerJob
```

`CancellationToken` uses `threading.Event`.

### Minimal tests

`test_gui_runtime_core.py` initially needs only:

1. One test covering the key model invariants above using parameterization.
2. One test confirming nested details are copied/frozen and runtime objects are rejected.
3. One test confirming `CancellationToken` is idempotent and thread-safe.
4. One test confirming the four WorkerJob adapters delegate to the expected Port method without rewriting the result.

### Verification

```powershell
python -m py_compile `
  .\pc\src\bootloader_upgrade_tool\gui\runtime_models.py `
  .\pc\src\bootloader_upgrade_tool\gui\runtime_ports.py `
  .\tests\unit\gui_runtime_fakes.py `
  .\tests\unit\test_gui_runtime_core.py

python -m pytest .\tests\unit\test_gui_runtime_core.py -q
```

### Commit

```bash
git add pc/src/bootloader_upgrade_tool/gui/runtime_models.py \
        pc/src/bootloader_upgrade_tool/gui/runtime_ports.py \
        tests/unit/gui_runtime_fakes.py \
        tests/unit/test_gui_runtime_core.py
git commit -m "feat(gui): add runtime models and port contracts"
```

---

## Task 2 — Worker and QThread execution boundary

### Files

Create:

```text
pc/src/bootloader_upgrade_tool/gui/workers.py
```

Modify:

```text
tests/unit/gui_runtime_fakes.py
tests/unit/test_gui_runtime_core.py
```

### Implement

Add immutable messages:

```text
WorkerProgressMessage
WorkerResultMessage
WorkerFinishedMessage
```

Add `TaskWorker(QObject)` with:

```text
progressReported = Signal(object)
resultReady = Signal(object)
workFinished = Signal(object)
```

Worker responsibilities:

1. Check cancellation before calling the Job.
2. Execute exactly one `WorkerJob`.
3. Forward progress inside `WorkerProgressMessage`.
4. Validate `TaskExecutionResult` type and task ID.
5. Convert unexpected exceptions to a `FAILED/RUNTIME_FATAL` result.
6. Emit exactly one result message.
7. Emit exactly one finished message from `finally`.
8. Never call `QThread.terminate()`.

### Minimal tests

Add only three Worker tests to `test_gui_runtime_core.py`:

1. Real QThread test: Job executes outside the GUI thread, emits one result and one finished message, and the thread exits cleanly.
2. Pre-cancel test: Job is not called and the result is `CANCELLED`.
3. Exception/invalid-result parameterized test: Worker returns a stable `RUNTIME_FATAL` result instead of leaking an exception.

Do not add separate tests for each message dataclass.

### Verification

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m py_compile .\pc\src\bootloader_upgrade_tool\gui\workers.py
python -m pytest .\tests\unit\test_gui_runtime_core.py -q
```

The run must not print:

```text
QThread: Destroyed while thread is still running
```

### Commit

```bash
git add pc/src/bootloader_upgrade_tool/gui/workers.py \
        tests/unit/gui_runtime_fakes.py \
        tests/unit/test_gui_runtime_core.py
git commit -m "feat(gui): add worker thread boundary"
```

---

## Task 3 — GuiController state machine

### Files

Create:

```text
pc/src/bootloader_upgrade_tool/gui/controller.py
tests/unit/test_gui_controller.py
```

Modify:

```text
tests/unit/gui_runtime_fakes.py
```

### Implement in two internal increments

The code may be implemented in two commits if review becomes difficult, but no artificial sub-batches are required.

### Increment A — Core lifecycle

Implement:

```text
initial DISCONNECTED snapshot
GUI-thread ownership
request_connect()
request_disconnect()
request_task()
request_cancel()
single-active-Task admission
per-generation QThread/Worker creation
PENDING -> RUNNING -> FINISHED
strict Step order and monotonic progress
weighted Overall progress
result_received + QThread.finished dual latch
Connect success/failure/cancel
local Task origin-state restoration
connected Task SHOW_ONLY handling
public Disconnect
```

The private active context shall contain:

```text
task_id
primary_plan
current_execution_plan
origin_runtime_state
execution_generation
cancellation token
Worker/QThread references
pending result
result_received
thread_finished
Step tracker
primary result
execution results
action history
```

### Increment B — Disposition and shutdown

Implement:

```text
ASK_DISCONNECT
KEEP_CONNECTION
internal Disconnect using same task_id and next generation
successful RELEASE_CONNECTION
Shutdown
Retry Cleanup
Force Exit
request_application_close()
global last_error policy
old-generation message discard
current-generation lifecycle violations -> RUNTIME_FATAL
wrong-thread public call -> queued fatal handling in GUI thread
```

### Minimal Controller tests

Use parameterization and scripted Fakes. Keep the file focused on externally observable behavior.

Mandatory cases:

1. **Connect matrix**: success -> `CONNECTED`; failure/cancel -> `DISCONNECTED`.
2. **Task admission matrix**: local Task from disconnected/connected; connected Task rejected while disconnected; second Task rejected while active.
3. **Cancellation**: token set, phase becomes `CANCELLING`, no thread termination, final `CANCELLED` or actual completed result preserved.
4. **Progress safety**: one valid weighted multi-Step case and one parameterized invalid-event case that enters `ERROR`.
5. **Dual latch**: result alone does not finalize; finalization occurs after real `QThread.finished`.
6. **ASK_DISCONNECT**: Keep returns to connected/suspect; Disconnect starts a new generation with the same task ID and ends disconnected.
7. **RELEASE_CONNECTION**: primary success remains success after automatic cleanup; cleanup failure becomes warning, not a fabricated operation error.
8. **Shutdown**: success emits `shutdownReady`; failure offers Retry/Force Exit and prevents ordinary work.
9. **Generation safety**: an old-generation queued message is ignored; a current-generation duplicate result is fatal.
10. **Wrong thread**: request is not executed and Controller enters `ERROR` through its GUI-thread violation signal.

Do not add one test per rejection code or every equivalent fatal code.

### Verification

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m py_compile .\pc\src\bootloader_upgrade_tool\gui\controller.py
python -m pytest .\tests\unit\test_gui_controller.py -q
```

Every test must wait for active QThreads to finish. No test may terminate a thread.

### Commit

Preferred single commit if the implementation remains reviewable:

```bash
git add pc/src/bootloader_upgrade_tool/gui/controller.py \
        tests/unit/test_gui_controller.py \
        tests/unit/gui_runtime_fakes.py
git commit -m "feat(gui): add controller runtime state machine"
```

Split into `core lifecycle` and `disposition flows` commits only when the diff is too large for reliable review.

---

## Task 4 — Modal TaskDialog

### Files

Create:

```text
pc/src/bootloader_upgrade_tool/gui/widgets/task_dialog.py
tests/unit/test_gui_task_dialog.py
```

Modify:

```text
tests/unit/test_gui_view_import_boundaries.py
```

### Implement

Public interface:

```text
TaskDialog(initial_state: TaskState, parent: QWidget)
apply_state(state: TaskState) -> None
cancelRequested(task_id: str)
actionRequested(task_id: str, action: TaskDialogAction)
```

Requirements:

```text
parented QDialog
WindowModal / modal
future integration uses open(), not exec()
one progress bar for single-Step Tasks
two progress bars for multi-Step Tasks
unknown progress is indeterminate
no invented percentages
close/title-bar/Esc while active requests cooperative cancellation and remains open
non-cancellable active Task cannot close
shows only TaskState.available_actions
one action click disables action buttons until next state
clean success may auto-close after 800 ms
warning/failure/cancel/decision requires manual acknowledgement
Task ID mismatch is rejected
```

The Dialog imports only PySide6 and `runtime_models.py`.

### Minimal tests

Only four tests are required:

1. Single-Step/multi-Step and indeterminate/determinate rendering in one parameterized test.
2. Active close/Esc emits one cancellation request and does not close; non-cancellable active state remains open.
3. Disposition actions reflect `available_actions` and suppress double activation.
4. Clean success auto-closes; failure/warning does not; another task ID is rejected.

Do not add pixel-geometry tests unless a real layout defect appears.

### View boundary update

Add `gui/widgets/task_dialog.py` to the existing View scan. Continue forbidding backend imports and additionally assert it does not import:

```text
controller
runtime_ports
workers
```

### Verification

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m py_compile .\pc\src\bootloader_upgrade_tool\gui\widgets\task_dialog.py
python -m pytest `
  .\tests\unit\test_gui_task_dialog.py `
  .\tests\unit\test_gui_view_import_boundaries.py `
  -q
```

### Commit

```bash
git add pc/src/bootloader_upgrade_tool/gui/widgets/task_dialog.py \
        tests/unit/test_gui_task_dialog.py \
        tests/unit/test_gui_view_import_boundaries.py
git commit -m "feat(gui): add modal runtime task dialog"
```

---

## Task 5 — Focused regression and validation evidence

### Files

Create:

```text
docs/phase11_2_batch11_validation.md
```

### Focused validation

```powershell
$env:QT_QPA_PLATFORM = "offscreen"

python -m pytest `
  .\tests\unit\test_gui_runtime_core.py `
  .\tests\unit\test_gui_controller.py `
  .\tests\unit\test_gui_task_dialog.py `
  .\tests\unit\test_gui_view_import_boundaries.py `
  -q
```

### Required existing regressions

Run the existing GUI static-layout and operation-library tests that protect Batch 11 boundaries:

```powershell
python -m pytest `
  .\tests\unit\test_gui_phase11_cleanup.py `
  .\tests\unit\test_gui_phase11_final_validation.py `
  .\tests\unit\test_gui_static_layout.py `
  .\tests\unit\test_gui_navigation.py `
  .\tests\unit\test_gui_program_pages.py `
  .\tests\unit\test_gui_settings_page.py `
  .\tests\unit\test_gui_advanced_page.py `
  .\tests\unit\test_gui_memory_pages.py `
  .\tests\unit\test_gui_logs_page.py `
  .\tests\unit\test_gui_flash_sectors.py `
  .\tests\unit\test_phase_10_8a_operations.py `
  -q
```

A full `pytest tests -q` run is recommended before merge but is not required after every development commit.

### Source boundary scan

Confirm the five production files do not import or invoke:

```text
serial
subprocess
cpu1_upgrade
UpgradeSession
BootProtocolClient
operations
images
transport
protocol
targets
QThread.terminate
```

Display-only names such as `transport_label` are allowed and must be reviewed manually if matched.

### Diff validation

```powershell
git diff --check
git status --short
```

The validation record must state explicitly:

```text
No real COM port was scanned or opened.
No SCI autobaud was performed.
No DSP command was transmitted.
No Flash or metadata operation was performed.
No RUN or RESET command was sent.
No CPU2 or W5300 runtime behavior was exercised.
```

### Commit

```bash
git add docs/phase11_2_batch11_validation.md
git commit -m "docs(gui): add Batch 11 runtime validation"
```

---

## 5. Stop conditions

Implementation must stop and return control to the user when any step would require:

```text
opening a real serial port
performing autobaud
connecting to a real DSP
erasing/programming/verifying Flash
writing metadata
issuing RUN or RESET
observing LEDs or physical target behavior
changing user-owned DSP initialization
changing linker or Flash layout
```

Do not substitute an invented simulator result for hardware evidence.

---

## 6. Completion criteria

Batch 11 is ready for review when:

1. The five production modules exist and follow the approved dependency direction.
2. All runtime work occurs outside the GUI thread.
3. Controller allows only one active GUI Task.
4. Cancellation is cooperative and no thread termination exists.
5. Worker result plus real thread completion is required before finalization.
6. Local Tasks can run while disconnected.
7. `ASK_DISCONNECT`, automatic connection release, and Shutdown are represented correctly.
8. TaskDialog cannot disappear while work or required disposition remains active.
9. The four focused test targets pass.
10. The selected Phase 11.1 and Phase 10.8A regressions pass.
11. No real hardware action occurred.

The next phase after this plan is implementation of Batch 11 only. MainWindow wiring and real RuntimeBackend integration remain separate reviewed batches.
