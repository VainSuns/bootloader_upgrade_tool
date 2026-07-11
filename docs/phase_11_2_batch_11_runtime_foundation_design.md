# Phase 11.2 Batch 11 GUI Runtime Foundation Design

## 1. Document status

```text
Status: DESIGN FROZEN — pending user review of this written document
Repository: VainSuns/bootloader_upgrade_tool
Validated baseline: 1f856ab5786ce3676897e8df560f0b885f9da4b1
Target: TMS320F28377D CPU1
GUI stack: Python 3.12 + PySide6 6.8+
```

This document freezes the design for **Phase 11.2 Batch 11 — Controller / Worker / Runtime State Foundation**.

Batch 11 creates only the reusable GUI runtime infrastructure. It does not connect a real serial port, run autobaud, execute a DSP command, modify Flash or metadata, run/reset the target, or bind the final MainWindow controls.

---

## 2. Design goals

Batch 11 shall provide a testable runtime foundation that later batches can use for:

```text
persistent SCI connection lifecycle
local image preparation and target-scoped caches
Advanced Diagnostics
Advanced Metadata
Advanced Flash operations
Advanced Execution operations
Program workflow
Memory reads
structured logs and Console progress
```

The foundation must preserve the validated Phase 10.8A operation-library semantics and the Phase 11.1 View boundary.

The required call path is:

```text
View intent
  -> GuiController
  -> WorkerJob
  -> RuntimePort / TaskPort
  -> later RuntimeBackend
  -> operations/*
  -> persistent UpgradeSession
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

The GUI View shall not duplicate protocol, Flash, service-attach, metadata, or upgrade workflow logic.

---

## 3. Non-negotiable project constraints

1. The default and current target is **TMS320F28377D**. No device-specific details from F280049, F28335, F28004x, or another C2000 device may be introduced.
2. DSP clocks, PLL, GPIO mux, SCI, EMIF, W5300, Flash wait-state, PIE, interrupts, watchdog, linker command files, and Flash layout remain user-controlled.
3. The Flash-resident bootloader does not statically link F021 or `flash_service_lib`.
4. The bootloader reads metadata only. Downloaded `flash_lib` performs Flash and metadata writes.
5. Confirmed-only auto-boot and current-image metadata binding remain unchanged.
6. PC is master and DSP is slave. SCI-A uses GPIO64/GPIO65 through RS232. SCI words are low byte then high byte. Autobaud uses ASCII `A` and echo `A`.
7. The GUI uses a persistent session and `operations/*`; it shall not run the legacy CLI as a subprocess.
8. CPU2 and W5300 runtime remain deferred.
9. Automated validation shall not perform any real hardware operation.

---

## 4. Batch 11 scope

### 4.1 Production files to create

```text
pc/src/bootloader_upgrade_tool/gui/runtime_models.py
pc/src/bootloader_upgrade_tool/gui/runtime_ports.py
pc/src/bootloader_upgrade_tool/gui/workers.py
pc/src/bootloader_upgrade_tool/gui/controller.py
pc/src/bootloader_upgrade_tool/gui/widgets/task_dialog.py
```

### 4.2 Test files to create

```text
tests/unit/gui_runtime_fakes.py
tests/unit/test_gui_runtime_models.py
tests/unit/test_gui_runtime_ports.py
tests/unit/test_gui_workers.py
tests/unit/test_gui_controller.py
tests/unit/test_gui_task_dialog.py
```

### 4.3 Existing test file allowed to change

```text
tests/unit/test_gui_view_import_boundaries.py
```

The boundary test shall include `gui/widgets/task_dialog.py` as a View module and continue forbidding imports of operations, images, session, transport, protocol, targets, serial, subprocess, and historical `program_controller`.

### 4.4 Explicitly outside Batch 11

```text
real RuntimeBackend implementation
real SCI connect/disconnect
real ASCII A autobaud
real UpgradeSession creation
real operations/* calls
real image preparation or cache population
MainWindow or SessionRibbon runtime wiring
Program/Advanced/Memory button binding
settings persistence
CPU2 runtime
W5300 runtime
DSP source changes
flash_lib changes
protocol payload changes
linker or Flash-layout changes
```

`gui/main_window.py`, `gui/widgets/ribbon/session_ribbon.py`, DSP code, linker files, protocol definitions, and operation implementations are not modified by Batch 11.

---

## 5. Module responsibilities and dependency direction

### 5.1 `runtime_models.py`

Contains only immutable enums and data models. It shall not import PySide6, operations, images, session, transport, protocol, targets, Worker, Controller, or View classes.

### 5.2 `runtime_ports.py`

Contains runtime Protocols, cancellation, progress callback types, and lightweight WorkerJob adapters. It shall not contain a real RuntimeBackend.

### 5.3 `workers.py`

Contains the QObject Worker and immutable Worker-to-Controller message envelopes. It calls one injected `WorkerJob` and knows nothing about runtime state, View, task admission, or business workflow selection.

### 5.4 `controller.py`

Contains `GuiController`, its private mutable active-task context, private execution-kind enum, progress state machine, request admission, QThread lifecycle, runtime transitions, and task disposition handling.

### 5.5 `widgets/task_dialog.py`

Contains only `TaskDialog`. It consumes `TaskState`, renders progress/results/actions, and emits user intent. It does not import Controller, Port, Worker, backend, operations, session, transport, protocol, targets, images, or serial.

### 5.6 Dependency direction

```text
runtime_models
    ^
runtime_ports
    ^
workers

runtime_models + runtime_ports + workers
    ^
controller

runtime_models
    ^
task_dialog
```

There is no reverse dependency from models or Dialog into Controller/backend layers.

---

## 6. Public runtime model

All GUI-owned public models use `@dataclass(frozen=True, slots=True)` unless they are enums or Protocols.

### 6.1 Runtime state

```text
RuntimeState
  DISCONNECTED
  CONNECTING
  CONNECTED
  BUSY
  DISCONNECTING
  ERROR
```

Meanings:

| State | Meaning | Accepted new intent |
|---|---|---|
| `DISCONNECTED` | No valid persistent session | Connect; local task with no connection requirement; immediate application close |
| `CONNECTING` | Connect Task active | Cancel current Task only |
| `CONNECTED` | Persistent session available and idle | Connected Task, local Task, Disconnect, application close |
| `BUSY` | A local or connected Task is active, or an uncertain-result decision is pending | Cancel or current disposition action only |
| `DISCONNECTING` | Disconnect, shutdown, or cleanup is active | No new Task; only shutdown failure actions when published |
| `ERROR` | Controller/Worker/Port/thread contract failure | Best-effort shutdown or force-exit path only |

`BUSY` does not imply that a connection exists. A local image-preparation Task may temporarily use `BUSY` while `connection_info` remains `None`.

### 6.2 Runtime snapshot

```text
RuntimeSnapshot
  state: RuntimeState
  active_task_id: str | None
  connection_info: ConnectionInfo | None
  active_target_key: str
  connection_suspect: bool
  disconnect_decision_pending: bool
  shutdown_requested: bool
  last_error: GuiRuntimeError | None
```

Batch 11 initializes `active_target_key` to `cpu1`. Batch 11 does not expose a target-selection API. A later batch may change the target without reconnecting.

Key invariants:

```text
state == DISCONNECTED
  -> connection_info is None
  -> connection_suspect is False
  -> disconnect_decision_pending is False

state == CONNECTED
  -> connection_info is not None

disconnect_decision_pending is True
  -> state == BUSY
  -> connection_suspect is True
  -> active_task_id is not None

state == ERROR
  -> last_error is not None
  -> last_error.disposition == RUNTIME_FATAL
```

### 6.3 Connection information

```text
ConnectionInfo
  connection_id: str
  transport_label: str
  endpoint_label: str
  connected_at: datetime
  details: Mapping[str, object]
```

All published timestamps, including `connected_at`, `started_at`, and `finished_at`, are timezone-aware UTC datetimes.

`ConnectionInfo` is a display/data snapshot only. It shall not contain `UpgradeSession`, transport, client, callback, QObject, file handle, lock, or any callable resource.

Target selection is intentionally not part of `ConnectionInfo`; CPU1/CPU2 selection is independent of the physical connection.

---

## 7. Task planning and progress model

### 7.1 Task connection requirement

```text
TaskConnectionRequirement
  NONE
  CONNECTED
```

- `NONE`: the Task may start from `DISCONNECTED` or `CONNECTED` and returns to its recorded origin runtime state.
- `CONNECTED`: the Task may start only from `CONNECTED` and normally returns to `CONNECTED`.

This is required for local app/service image preparation before a hardware connection exists.

### 7.2 Task phases

```text
TaskPhase
  PENDING
  RUNNING
  CANCELLING
  FINISHED
```

- `PENDING`: accepted and published to View, but the QThread has not yet been successfully submitted.
- `RUNNING`: QThread start was successfully submitted; Port invocation may not yet have begun.
- `CANCELLING`: cancellation requested; the current operation continues until a safe Port boundary.
- `FINISHED`: the current execution generation has completed or the Task is waiting for a post-execution decision.

An internal cleanup generation may transition the same GUI Task from `FINISHED` back to `RUNNING` without emitting a second `taskStarted` signal.

### 7.3 Task disposition state

```text
TaskDispositionState
  NONE
  AWAITING_DISCONNECT_DECISION
  DISCONNECTING
  COMPLETE
```

- `NONE`: no disconnect-decision subflow is active; also used while a shutdown failure awaits Retry Cleanup / Force Exit.
- `AWAITING_DISCONNECT_DECISION`: operation result is uncertain and the user must choose Disconnect or Keep Connection.
- `DISCONNECTING`: an internal, non-cancellable connection-release generation is running.
- `COMPLETE`: the entire GUI Task, including required disposition and cleanup, is complete.

`taskFinished` is emitted only after disposition becomes `COMPLETE`.

### 7.4 Plan and step types

```text
ProgressMode
  INDETERMINATE
  DETERMINATE

TaskStepState
  STARTED
  PROGRESS
  COMPLETED

CompletionPolicy
  AUTO_CLOSE_ON_CLEAN_SUCCESS
  REQUIRE_ACKNOWLEDGEMENT
```

```text
TaskStepPlan
  step_id: str
  title: str
  initial_progress_mode: ProgressMode
  weight: int = 1
```

```text
TaskPlan
  task_id: str
  title: str
  steps: tuple[TaskStepPlan, ...]
  connection_requirement: TaskConnectionRequirement
  cancellable: bool
  completion_policy: CompletionPolicy
```

Validation rules:

```text
task_id matches the Controller-generated ID
title is non-empty
at least one step exists
every step_id is non-empty and unique
every step title is non-empty
every weight is greater than zero
total weight is greater than zero
all enum fields are valid
```

### 7.5 Task progress update

```text
TaskProgressUpdate
  task_id: str
  step_id: str
  step_state: TaskStepState
  stage: str
  message: str
  current: int | None
  total: int | None
  progress_mode: ProgressMode
  raw_event: object | None
  details: Mapping[str, object]
```

The Port explicitly reports Step `STARTED`, `PROGRESS`, and `COMPLETED`. Controller never infers Step completion from operation names, stage strings, or `current == total`.

`raw_event` preserves the complete Phase 10.8A `ProgressEvent` when present.

### 7.6 Task state

```text
TaskState
  task_id: str
  plan: TaskPlan
  phase: TaskPhase
  disposition_state: TaskDispositionState
  current_step_index: int | None
  current_step_id: str | None
  current_step_title: str
  message: str
  overall_current: int
  overall_total: int
  step_current: int
  step_total: int
  step_progress_mode: ProgressMode
  cancel_requested: bool
  available_actions: tuple[TaskDialogAction, ...]
  close_allowed: bool
  auto_close_delay_ms: int | None
  started_at: datetime | None
  finished_at: datetime | None
  result: TaskExecutionResult | None
  error: GuiRuntimeError | None
```

`overall_total` is fixed at `1000`. Controller calculates `overall_current` from Step weights. Unknown current-Step progress contributes zero within that Step until the Step reports `COMPLETED`.

For an internal cleanup generation, `TaskState.plan` is the current execution plan shown by the Dialog, while the private Controller context retains the original primary plan and result.

---

## 8. Result, warning, and error model

### 8.1 Final status

```text
TaskFinalStatus
  SUCCEEDED
  FAILED
  CANCELLED
  COMPLETED_AFTER_CANCEL_REQUEST
```

Rules:

- `CANCELLED`: cancellation took effect at a safe boundary before remaining Steps.
- `COMPLETED_AFTER_CANCEL_REQUEST`: cancellation was requested but the already-running non-interruptible operation completed successfully.
- An operation failure remains `FAILED` even if cancellation had also been requested.

### 8.2 Completion action

```text
TaskCompletionAction
  NONE
  RELEASE_CONNECTION
```

`RELEASE_CONNECTION` expresses a successful operation, such as RUN or RESET ACK, after which the persistent session must be released and caches cleared. It is not an error disposition.

A successful result with `RELEASE_CONNECTION` causes Controller to start a non-cancellable internal connection-release generation using the same `task_id`.

### 8.3 Error disposition

```text
ErrorDisposition
  SHOW_ONLY
  ASK_DISCONNECT
  FORCE_DISCONNECTED
  RUNTIME_FATAL
```

- `SHOW_ONLY`: display the Task error and preserve the current connection state.
- `ASK_DISCONNECT`: result is uncertain; ask the user whether to disconnect.
- `FORCE_DISCONNECTED`: actual transport/session loss or a condition that makes the connection unusable.
- `RUNTIME_FATAL`: Controller/Worker/Port/thread lifecycle or contract error; enter global `ERROR`.

### 8.4 Structured errors and warnings

```text
GuiRuntimeError
  code: str
  message: str
  stage: str
  disposition: ErrorDisposition
  task_id: str | None
  recoverable: bool
  outcome_uncertain: bool
  details: Mapping[str, object]
  cause_summary: str | None
```

```text
GuiTaskWarning
  code: str
  message: str
  stage: str
  details: Mapping[str, object]
```

Invariants:

```text
ASK_DISCONNECT -> outcome_uncertain is True
RUNTIME_FATAL -> recoverable is False
SHOW_ONLY -> no automatic connection release
FORCE_DISCONNECTED -> Controller clears its connection snapshot
```

### 8.5 Task execution result

```text
TaskExecutionResult
  task_id: str
  status: TaskFinalStatus
  summary: str
  message: str
  step_results: tuple[object, ...]
  payload: object | None
  warning: GuiTaskWarning | None
  error: GuiRuntimeError | None
  completion_action: TaskCompletionAction
  cancel_requested: bool
  started_at: datetime | None
  finished_at: datetime
```

Invariants:

```text
SUCCEEDED -> error is None
FAILED -> error is not None
CANCELLED -> cancel_requested is True
COMPLETED_AFTER_CANCEL_REQUEST -> cancel_requested is True and error is None
FAILED does not also carry a warning
finished_at >= started_at when started_at is present
RELEASE_CONNECTION is valid only for a non-failed connected Task result
```

`step_results` preserves all underlying `OperationResult` objects without reducing them to booleans or summaries. `payload` carries the Task-level product, such as `ConnectionInfo`, `PreparedFlashImage`, or a diagnostics snapshot.

---

## 9. Immutable-data boundary

GUI-owned Mapping fields shall be defensively copied and recursively frozen to JSON-safe values:

```text
None
bool
int
float
str
tuple
read-only Mapping
```

They shall reject QObject, `UpgradeSession`, transport/client objects, callbacks, arbitrary callables, file handles, and other mutable runtime resources.

Phase 10.8A `OperationResult` and `ProgressEvent` currently contain nested dictionaries. Ports shall treat them as read-only after publication and perform defensive copying when needed. Controller and View do not mutate them.

---

## 10. Requests, Ports, cancellation, and WorkerJobs

### 10.1 Request contract

```python
class GuiTaskRequest(Protocol):
    def create_plan(self, task_id: str) -> TaskPlan: ...
```

Formal request implementations are frozen, slotted dataclasses. `create_plan()` is a pure function and shall not access files, session, transport, operation functions, hardware, QWidget, or global mutable state.

Batch 11 does not define the final serial connection fields. Real connect-request fields are frozen in Batch 12.

### 10.2 Cancellation token

`CancellationToken` is backed by `threading.Event` and provides:

```text
request_cancel()
is_cancel_requested()
```

Cancellation is cooperative. No code may use `QThread.terminate()`.

- Controller accepts cancellation only when `TaskPlan.cancellable` is true.
- Port checks cancellation at safe boundaries.
- No packet/chunk-level cancellation is promised.
- Disconnect, shutdown, and internal resource release are not cancellable.

### 10.3 Port protocols

```text
RuntimePort.connect(task_id, request, cancellation, progress)
  -> TaskExecutionResult

RuntimePort.disconnect(task_id, request, cancellation, progress)
  -> TaskExecutionResult

RuntimePort.shutdown(task_id, request, cancellation, progress)
  -> TaskExecutionResult

TaskPort.execute(task_id, request, cancellation, progress)
  -> TaskExecutionResult
```

All expected business, validation, communication, timeout, closed-transport, and cancellation outcomes are mapped by the Port to `TaskExecutionResult`.

Only programming/contract failures may escape the Port and be converted by Worker to `RUNTIME_FATAL`.

Connect success must return a valid `ConnectionInfo` payload. Disconnect and shutdown success normally return no payload.

### 10.4 WorkerJob adapters

```text
ConnectWorkerJob       -> RuntimePort.connect()
DisconnectWorkerJob    -> RuntimePort.disconnect()
ShutdownWorkerJob      -> RuntimePort.shutdown()
TaskWorkerJob          -> TaskPort.execute()
```

Every Job implements one narrow Protocol:

```text
execute(cancellation, progress) -> TaskExecutionResult
```

A Job does not create threads, change Controller state, interpret operation semantics, or access QWidget.

---

## 11. Persistent backend ownership and threading

A later real `RuntimeBackend` may implement both `RuntimePort` and `TaskPort` so that both interfaces share one persistent session and target-scoped caches.

The backend owns:

```text
UpgradeSession
ByteTransport
protocol client state
connection snapshot source
prepared CPU1/CPU2 app caches
prepared service cache
```

Controller owns none of those resources.

The backend is a normal Python object, not a QObject. It is thread-neutral and may be entered sequentially by different per-Task Worker threads.

Serial access is protected by:

1. Controller's single-active-Task rule.
2. A backend non-blocking `threading.Lock` as a contract guard.

Concurrent backend entry is a `RUNTIME_FATAL` contract failure, not a condition to wait on indefinitely.

Progress callbacks shall only publish immutable `TaskProgressUpdate` data. They shall not re-enter the backend or initiate another operation.

---

## 12. Worker design

### 12.1 Per-execution thread model

Each execution generation creates a fresh:

```text
TaskWorker(QObject) + QThread
```

Controller retains strong references until the actual `QThread.finished` signal.

The same GUI Task may have multiple generations:

```text
primary operation
internal connection release
shutdown cleanup retry
```

### 12.2 Worker messages

```text
WorkerProgressMessage
  task_id
  execution_generation
  update

WorkerResultMessage
  task_id
  execution_generation
  result

WorkerFinishedMessage
  task_id
  execution_generation
```

Qt signals use `Signal(object)`. Controller validates the actual dataclass type, task ID, and generation.

### 12.3 Worker run contract

Worker shall:

1. Check cancellation before invoking the Job.
2. If already cancelled and cancellable, create a `CANCELLED` result without calling the Port.
3. Call exactly one `WorkerJob.execute()`.
4. Validate that the return type is `TaskExecutionResult` and `result.task_id` matches.
5. Convert an unexpected exception or invalid result contract to a `FAILED/RUNTIME_FATAL` result.
6. Emit exactly one `resultReady` message.
7. Emit exactly one `workFinished` message in `finally`.

`workFinished` triggers `QThread.quit()`, but does not mean that the thread has exited. The normal cleanup wiring is `workFinished -> thread.quit`, `workFinished -> worker.deleteLater`, and `thread.finished -> thread.deleteLater`; Controller still retains strong references until `thread.finished`.

### 12.4 Completion latch

Controller finalizes a generation only when both facts are true:

```text
result_received is True
AND
QThread.finished has occurred
```

Contract violations:

```text
thread exited without a result -> WORKER_EXITED_WITHOUT_RESULT
second result for current generation -> DUPLICATE_WORKER_RESULT
progress after result for current generation -> PROGRESS_AFTER_RESULT
invalid Worker message type -> INVALID_WORKER_MESSAGE_TYPE
```

They produce `RUNTIME_FATAL`.

Queued messages from an older generation of the same Task are logged and discarded. A message for an unknown Task or a future generation is `RUNTIME_FATAL`.

A fatal condition never causes forced thread destruction. Controller latches the fatal state, refuses new work, keeps Worker/QThread references, and waits for real `QThread.finished`.

---

## 13. Controller design

### 13.1 Thread ownership

`GuiController` is a QObject created and retained in the QApplication GUI thread. It is never moved to another thread.

All public request/action methods must be called from the GUI thread.

A wrong-thread call:

1. Does not execute or queue the original request.
2. Returns a structured fatal result to the caller.
3. Emits a private queued `_threadViolationDetected` signal.
4. Lets a GUI-thread slot enter `RuntimeState.ERROR` and emit `runtimeErrorRaised`.

This preserves Qt thread-affinity rules while still treating the misuse as fatal.

### 13.2 Public request APIs

```text
request_connect(request) -> RequestAdmission
request_disconnect(request) -> RequestAdmission
request_task(request) -> RequestAdmission
request_cancel(task_id) -> CancelRequestResult
respond_task_action(task_id, action) -> TaskActionResult
request_application_close() -> ApplicationCloseResult
```

Connect, Disconnect, ordinary Task, and Shutdown all use the common Task/Worker/Dialog foundation, but use distinct Controller entry points and execution kinds.

### 13.3 Public signals

```text
runtimeStateChanged(RuntimeSnapshot)

taskStarted(TaskState)
taskProgressed(TaskProgressUpdate)
taskStateChanged(TaskState)
taskFinished(TaskExecutionResult)

requestRejected(RequestRejection)
runtimeErrorRaised(GuiRuntimeError)

shutdownReady()
forceExitReady(GuiRuntimeError | None)
```

There is no separate `disconnectDecisionRequired` signal. The decision is represented by `TaskState.disposition_state`, `available_actions`, and the result error.

All public signals are emitted from the GUI thread.

### 13.4 Request admission models

```text
RequestAdmission
  accepted
  task_id
  rejection
  error
```

Exactly one of these cases is valid:

```text
accepted Task -> task_id only
normal admission rejection -> rejection only
pre-start fatal -> error only
```

```text
RequestRejectionCode
  INVALID_RUNTIME_STATE
  TASK_ALREADY_ACTIVE
  DECISION_PENDING
  SHUTDOWN_IN_PROGRESS
  UNKNOWN_TASK
  TASK_NOT_CANCELLABLE
  ACTION_NOT_AVAILABLE
  ACTION_ALREADY_APPLIED
  CLOSE_NOT_ALLOWED
```

Normal admission rejection does not create a Task, does not write `last_error`, and does not enter `ERROR`.

Dedicated results are used for cancellation, Task actions, and application close:

```text
CancelRequestResult
  accepted: bool
  task_id: str
  already_requested: bool
  rejection: RequestRejection | None
  error: GuiRuntimeError | None

TaskActionResult
  accepted: bool
  task_id: str
  action: TaskDialogAction
  already_applied: bool
  rejection: RequestRejection | None
  error: GuiRuntimeError | None

ApplicationCloseResult
  decision: ApplicationCloseDecision
  task_id: str | None
  rejection: RequestRejection | None
  error: GuiRuntimeError | None
```

For these result types, normal state rejection uses `rejection`; wrong-thread or internal Controller failure uses `error`. The two fields are mutually exclusive.

Repeated cancellation is an idempotent success with `already_requested=True`. Repeated Disconnect/Keep/Force Exit actions are idempotently protected from duplicate Worker creation or duplicate signals.

### 13.5 Private active-task context

Controller keeps exactly one private mutable context:

```text
_ActiveTaskContext
  task_id
  request
  primary_plan
  current_execution_plan
  primary_result
  execution_results
  origin_runtime_state
  state
  cancellation
  job
  worker
  thread
  pending_result
  result_received
  thread_finished
  disposition_state
  action_history
  execution_generation
  current execution Step tracker
```

No Task history or completed-result registry is added in Batch 11.

The context is retained while awaiting a disconnect decision, running internal release, or waiting for shutdown retry/force-exit disposition. It is cleared only after the entire Task is complete.

### 13.6 Execution kinds

Private `ExecutionKind` values:

```text
CONNECT
TASK
DISCONNECT
SHUTDOWN
INTERNAL_DISCONNECT
```

Shutdown retry remains `SHUTDOWN` with a higher generation.

Controller records the kind explicitly. It never infers kind from a Request class name, title, Job implementation, or error text.

### 13.7 Task start sequence

For a valid request:

```text
1. Check admission.
2. Generate uuid.uuid4().hex task_id.
3. Call request.create_plan(task_id).
4. Validate the plan.
5. Construct WorkerJob, TaskWorker, QThread, and signal connections.
6. Create ActiveTaskContext.
7. Publish new RuntimeSnapshot.
8. Emit taskStarted(PENDING).
9. Call QThread.start().
10. After successful submission, emit taskStateChanged(RUNNING).
```

Failures before Step 6 are pre-start `RUNTIME_FATAL`: no `taskStarted` and no TaskDialog.

If `QThread.start()` fails after `taskStarted`, Controller creates a task-scoped fatal result, transitions the published Task to `FINISHED`, safely releases unstarted resources, enters global `ERROR`, and lets the existing Dialog show the failure.

### 13.8 Single-Task rule

No second GUI Task may start while an active context exists, including:

```text
Worker running
result received but thread not finished
ASK_DISCONNECT decision pending
internal disconnect active
shutdown cleanup failed awaiting action
```

The execution lock is not released merely because `resultReady` was received.

### 13.9 Local Task admission

A `TaskConnectionRequirement.NONE` request is accepted from `DISCONNECTED` or `CONNECTED`.

Controller records `origin_runtime_state`, transitions to `BUSY`, and restores the origin state after normal completion/cancellation/failure.

A local Task may not return `ASK_DISCONNECT`, `FORCE_DISCONNECTED`, or `RELEASE_CONNECTION`. Such a combination is a Port contract error.

### 13.10 Connected Task admission

A `TaskConnectionRequirement.CONNECTED` request is accepted only from `CONNECTED` and transitions to `BUSY`.

Normal completion returns to `CONNECTED`, unless the result requires disconnect, forces disconnect, or enters a post-result decision.

---

## 14. Strict Step state machine

For each current execution plan, Controller accepts only:

```text
not started
  -> STARTED
  -> PROGRESS zero or more times
  -> COMPLETED
```

Rules:

1. Steps execute in `TaskPlan.steps` order.
2. A later Step cannot start before the previous Step completes.
3. A completed Step cannot restart.
4. `PROGRESS` requires the current Step to be started and incomplete.
5. Determinate progress requires `total > 0` and `0 <= current <= total`.
6. Current progress cannot decrease.
7. Once a determinate total is established, it cannot change.
8. `INDETERMINATE -> DETERMINATE` is allowed.
9. `DETERMINATE -> INDETERMINATE` is forbidden.
10. Duplicate `STARTED` or `COMPLETED` is fatal.
11. A `SUCCEEDED` or `COMPLETED_AFTER_CANCEL_REQUEST` generation must have completed all Steps.
12. `FAILED` and `CANCELLED` may leave current and future Steps incomplete.

Overall progress formula:

```text
(completed_step_weights
 + current_step_weight * current_step_fraction)
 / total_step_weights
```

An indeterminate current Step contributes zero until completion, then contributes its full weight.

After a valid progress message, signal order is:

```text
taskProgressed(update)
taskStateChanged(new_state)
```

Invalid progress does not emit either public signal.

---

## 15. Result handling and runtime transitions

### 15.1 Connect

```text
DISCONNECTED -> CONNECTING
```

- Success requires `ConnectionInfo`, stores it, clears global `last_error`, and enters `CONNECTED`.
- Failure or cancellation releases all partially created runtime resources and enters `DISCONNECTED`.
- A normal connect failure remains in the Task result and does not write global `last_error`.
- `RUNTIME_FATAL` enters `ERROR`.
- `ASK_DISCONNECT` and `RELEASE_CONNECTION` are illegal Connect results.

### 15.2 Ordinary local Task

```text
DISCONNECTED or CONNECTED -> BUSY -> origin state
```

It cannot affect connection state. Connection-related dispositions are contract violations.

### 15.3 Ordinary connected Task

```text
CONNECTED -> BUSY
```

- Clean success/failure/cancellation with `SHOW_ONLY` returns to `CONNECTED`.
- `ASK_DISCONNECT` enters the decision flow.
- `FORCE_DISCONNECTED` clears connection state and enters `DISCONNECTED`.
- `RUNTIME_FATAL` enters `ERROR`.
- `RELEASE_CONNECTION` starts internal release.

### 15.4 ASK_DISCONNECT flow

After the primary Worker and thread complete:

```text
TaskPhase = FINISHED
TaskDispositionState = AWAITING_DISCONNECT_DECISION
RuntimeState = BUSY
connection_suspect = True
disconnect_decision_pending = True
available_actions = (DISCONNECT, KEEP_CONNECTION)
close_allowed = False
```

No `taskFinished` is emitted yet.

#### Keep Connection

```text
RuntimeState = CONNECTED
connection_suspect = True
disconnect_decision_pending = False
disposition = COMPLETE
```

The final Task remains failed/uncertain. It is not automatically retried. `connection_suspect` remains true until an explicit Disconnect or a later successful Connect establishes a fresh session.

#### Disconnect

Controller:

1. Clears available actions.
2. Increments `execution_generation`.
3. Replaces `current_execution_plan` with a single non-cancellable `Release Connection` plan.
4. Sets `TaskPhase=RUNNING` and `TaskDispositionState=DISCONNECTING`.
5. Starts `InternalDisconnectWorkerJob` using the same `task_id` and Dialog.

After best-effort cleanup, runtime enters `DISCONNECTED` even if cleanup partially fails. The primary uncertain error remains the final error. Internal cleanup evidence is appended to `step_results`; cleanup failure is added to final details and does not overwrite the original timeout cause.

### 15.5 Successful RELEASE_CONNECTION flow

Used for successful RUN/RESET ACK:

1. Preserve the successful primary result.
2. Start the same internal non-cancellable release generation described above.
3. Enter `DISCONNECTED` after best-effort cleanup.
4. Clear connection snapshot and caches.
5. If cleanup fails, keep the primary status successful but attach a structured cleanup warning and require user acknowledgement.
6. Emit `taskFinished` only after cleanup completes.

### 15.6 User Disconnect

```text
CONNECTED -> DISCONNECTING -> DISCONNECTED
```

Disconnect is non-cancellable. Success or cleanup failure both end in `DISCONNECTED` and clear the Controller connection snapshot.

A Disconnect result of `CANCELLED`, `COMPLETED_AFTER_CANCEL_REQUEST`, `ASK_DISCONNECT`, or `RELEASE_CONNECTION` is a Port contract error.

Cleanup failure is retained in the Task result and global `last_error`, but the user may explicitly connect again after closing the Dialog.

### 15.7 Application shutdown

`request_application_close()` returns:

```text
ALLOW_IMMEDIATE
SHUTDOWN_STARTED
REJECTED
ERROR
```

- `DISCONNECTED` with no active Task -> `ALLOW_IMMEDIATE`.
- `CONNECTED` and idle -> set `shutdown_requested`, start non-cancellable Shutdown Task, enter `DISCONNECTING`.
- `CONNECTING`, `BUSY`, or an active `DISCONNECTING` generation -> reject close.
- `ERROR` with no active Worker -> start best-effort Shutdown.
- `ERROR` with an active Worker -> reject until the Worker exits.

Shutdown success:

```text
RuntimeState = DISCONNECTED
last_error = None
TaskDispositionState = COMPLETE
emit shutdownReady() exactly once
```

Shutdown failure:

```text
RuntimeState = DISCONNECTING
shutdown_requested = True
connection_info = None
TaskPhase = FINISHED
TaskDispositionState = NONE
available_actions = (RETRY_CLEANUP, FORCE_EXIT)
close_allowed = False
```

`RETRY_CLEANUP` increments the generation, replaces the current plan with a fresh cleanup plan, sets `RUNNING`, and starts another Shutdown Worker.

`FORCE_EXIT` emits `forceExitReady(error)` exactly once. It does not claim that runtime resources were cleanly released.

### 15.8 Global last-error policy

`RuntimeSnapshot.last_error` records only errors that affect the global runtime:

```text
FORCE_DISCONNECTED
RUNTIME_FATAL
shutdown cleanup failure
user Disconnect cleanup failure
```

Ordinary Task failure, `SHOW_ONLY`, `ASK_DISCONNECT`, cancellation, and request rejection remain in Task-level results.

Successful Connect, normal Disconnect, and successful Shutdown clear global `last_error`.

After `RUNTIME_FATAL`, direct reconnect is forbidden. Only safe shutdown/retry/force-exit paths remain available.

---

## 16. Finalization and signal order

When a generation has both result and real thread completion, Controller handles the result. If no additional disposition generation is needed, final Task completion order is:

```text
1. Construct the final aggregated TaskExecutionResult.
2. Construct final TaskState with phase FINISHED and disposition COMPLETE.
3. Clear Worker/QThread and ActiveTaskContext ownership.
4. Set RuntimeSnapshot.active_task_id = None and final runtime state.
5. Emit final taskStateChanged(final_state).
6. Emit runtimeStateChanged(final_snapshot) when changed.
7. Emit taskFinished(final_result).
8. Emit shutdownReady or forceExitReady when applicable.
```

The active context is cleared before `taskFinished`; a `taskFinished` listener may therefore immediately request the next valid Task.

Controller shall not emit a new signal when the immutable snapshot is identical to the previously published snapshot.

---

## 17. TaskDialog design

### 17.1 Public interface

```text
TaskDialog(initial_state: TaskState, parent: QWidget)
apply_state(state: TaskState) -> None

cancelRequested(task_id: str)
actionRequested(task_id: str, action: TaskDialogAction)
```

The Dialog rejects a state whose `task_id` differs from its initial Task.

### 17.2 Modal behavior

The Dialog is parented to the main View and uses non-blocking Qt modality through `open()`/window modality. It shall not call `exec()` and create a nested event loop.

### 17.3 Progress presentation

- Single Step with unknown progress: one indeterminate progress bar.
- Single Step with known progress: one determinate progress bar.
- Multiple Steps: Overall and Current Step bars.
- An unknown current Step keeps Overall at the Step start until completion.
- A current Step may switch from indeterminate to determinate.
- Dialog never invents a percentage.

### 17.4 Cancellation and closing

- `TaskPlan.cancellable=True` and not yet cancelled -> show enabled Cancel.
- After cancellation request -> disable Cancel and show that cancellation is waiting for a safe stop point.
- A close button, title-bar close, or Esc while `close_allowed=False` does not close the Dialog.
- If cancellation is available and has not been requested, such a close attempt emits one `cancelRequested` and remains open.
- For a non-cancellable or already-cancelling Task, the close attempt is ignored without another signal.
- `reject()` and Esc handling must obey the same `close_allowed` rule as `closeEvent()`.

### 17.5 Disposition actions

```text
TaskDialogAction
  DISCONNECT
  KEEP_CONNECTION
  RETRY_CLEANUP
  FORCE_EXIT
```

The Dialog displays exactly `TaskState.available_actions`. It does not infer actions from an error code or title.

After one action click, the Dialog temporarily disables all action buttons until the next state arrives. Controller remains the final idempotency guard.

### 17.6 Completion and auto-close

`CLOSE` is not a Controller action. It is local Dialog behavior.

- Clean success + `AUTO_CLOSE_ON_CLEAN_SUCCESS` + no warning -> `close_allowed=True`, `auto_close_delay_ms=800`.
- Warning, failure, cancellation, completed-after-cancel, or `REQUIRE_ACKNOWLEDGEMENT` -> manual Close.
- Pending decision, cleanup, or shutdown failure -> close remains forbidden.

A single-shot QTimer performs the 800 ms close. A new state that removes close permission or the delay cancels the timer. Re-applying the same state does not create duplicate timers.

### 17.7 Result display

The primary area shows:

```text
result.summary
result.message
warning or error headline
```

`step_results`, error details, and warning details are displayed only in an expandable details area. `raw_event` is not retained by TaskDialog; it is available to Console/log listeners through `taskProgressed`. Dialog does not interpret DSP business semantics.

---

## 18. Real-backend prerequisites for later batches

These items are intentionally not implemented in Batch 11, but are mandatory before real runtime binding.

### 18.1 Stable transport error classification

The existing operation layer currently collapses transport timeout, transport closed, and some protocol failures into a generic error. Before real TaskPort integration, operation results must preserve stable categories at least equivalent to:

```text
TRANSPORT_TIMEOUT
TRANSPORT_CLOSED
TRANSPORT_IO_ERROR
PROTOCOL_DECODE_ERROR
DSP_STATUS_ERROR
```

The TaskPort must map categories to `ASK_DISCONNECT`, `FORCE_DISCONNECTED`, or `SHOW_ONLY` without inspecting human-readable error strings.

This change shall preserve Phase 10.8A regression behavior and shall be implemented in a later explicit batch, not Batch 11.

### 18.2 Cooperative Connect cancellation

The current serial open/autobaud implementation does not accept a cancellation check. Batch 12 must add a PC-side cancellation hook at safe points:

```text
serial settle wait intervals
before each ASCII A send
following each echo read
before post-autobaud delay
```

Cancellation must close a partially opened serial resource, clear backend references, and return `CANCELLED`.

No DSP initialization change is required.

### 18.3 Application composition point

Current active GUI launch composition is in `gui/app.py`; `gui/application.py` is a compatibility wrapper. The existing View boundary test treats `app.py` as a View module.

Batch 11 performs no real composition. A later Connect batch shall explicitly decide whether to:

```text
use a thin non-View bootstrap/composition module
or revise the entrypoint boundary with dedicated tests
```

A real backend shall not be silently imported into an existing View module in violation of the boundary test.

### 18.4 Target-scoped preparation caches

The later backend shall maintain separate app caches for stable target keys:

```text
cpu1
cpu2
```

and a service preparation cache. Disconnect clears all prepared caches. Target switching does not itself invalidate another target's cache.

---

## 19. Test design

All Fake objects and fault injection utilities live only in `tests/unit/gui_runtime_fakes.py`.

### 19.1 Runtime model tests

Cover:

```text
TaskPlan validation
unique Step IDs and positive weights
recursive immutable details
TaskExecutionResult invariants
RuntimeSnapshot invariants
ConnectionInfo resource rejection
admission/result mutual exclusivity
local vs connected Task requirements
```

### 19.2 Port and Job tests

Cover:

```text
CancellationToken thread safety and idempotency
all four WorkerJob adapters call the correct Port method
arguments and callbacks are forwarded unchanged
Job does not rewrite TaskExecutionResult
```

### 19.3 Worker tests

Cover:

```text
one resultReady and one workFinished
workFinished always emitted from finally
pre-invocation cancellation does not call Job
unexpected Job exception -> RUNTIME_FATAL
invalid return type -> RUNTIME_FATAL
wrong result task_id -> RUNTIME_FATAL
correct task_id and generation envelopes
Job executes on Worker thread
```

### 19.4 Controller tests

Cover at minimum:

```text
six RuntimeState values and legal transitions
Connect success/failure/cancel
local Task from DISCONNECTED and CONNECTED
connected Task success/failure/cancel
single-active-Task admission
PENDING/RUNNING/CANCELLING/FINISHED
strict Step ordering and monotonic progress
weighted Overall calculation
success with incomplete Plan -> fatal
result + QThread.finished dual latch
thread exit without result
current-generation duplicate result and progress-after-result
old-generation queued message discard
future/unknown generation fatal
ASK_DISCONNECT Keep and Disconnect paths
internal disconnect same task_id and new generation
successful RELEASE_CONNECTION path
Disconnect cleanup failure -> DISCONNECTED
Shutdown success/failure/retry/force-exit
Controller wrong-thread call handling
pre-task startup fatal vs post-taskStarted QThread.start failure
application close admission
final signal order and ActiveTaskContext cleanup
```

### 19.5 TaskDialog tests

Cover:

```text
single and multiple progress layouts
indeterminate-to-determinate transition
Cancel button state
close/title-bar/Esc cooperative cancel behavior
non-cancellable close rejection
available disposition actions only
button double-click suppression
close_allowed behavior
800 ms auto-close
Timer cancellation on state change
task_id mismatch rejection
warning/error/details rendering
no forbidden runtime imports
```

### 19.6 Regression tests

Run all existing:

```text
Phase 11.1 GUI tests
layout preview tests
View import-boundary test
Phase 10.8A operation tests
```

No test may open a real COM port, instantiate a real serial transport, run autobaud, call real DSP operations, write Flash/metadata, issue RUN/RESET, or require hardware observation.

---

## 20. Validation commands

Implementation validation shall include:

```text
python -m py_compile \
  pc/src/bootloader_upgrade_tool/gui/runtime_models.py \
  pc/src/bootloader_upgrade_tool/gui/runtime_ports.py \
  pc/src/bootloader_upgrade_tool/gui/workers.py \
  pc/src/bootloader_upgrade_tool/gui/controller.py \
  pc/src/bootloader_upgrade_tool/gui/widgets/task_dialog.py

pytest tests/unit/test_gui_runtime_models.py -v
pytest tests/unit/test_gui_runtime_ports.py -v
pytest tests/unit/test_gui_workers.py -v
pytest tests/unit/test_gui_controller.py -v
pytest tests/unit/test_gui_task_dialog.py -v
pytest tests/unit/test_gui_view_import_boundaries.py -v
pytest tests -v
git diff --check
```

Validation evidence must explicitly state that no real hardware operation was performed.

---

## 21. Acceptance criteria

Batch 11 is complete only when all of the following are true:

1. The five production modules and six focused test-support/test modules exist with the responsibilities defined above.
2. Controller is GUI-thread bound and all Port work occurs in a Worker thread.
3. Only one active GUI Task exists at a time, including pending decisions and cleanup retries.
4. Connect, Disconnect, Shutdown, local Task, and connected Task flows are fully covered with Fake Ports.
5. Cancellation is cooperative and no forced thread termination exists.
6. Worker completion uses both a result and real `QThread.finished`.
7. Current-generation lifecycle violations enter `ERROR`; old-generation queued messages are harmlessly discarded.
8. Strict Step ordering and weighted progress are enforced.
9. Local image-preparation Tasks can later run while disconnected.
10. Successful RUN/RESET can later release the connection without being represented as an error.
11. `ASK_DISCONNECT`, internal cleanup, Shutdown retry, and force-exit are representable without a second MainWindow or hidden background Worker.
12. TaskDialog cannot close while work or required disposition is active.
13. Existing View import boundaries and Phase 11.1 layout behavior do not regress.
14. No real backend, hardware action, DSP modification, protocol change, linker change, or Flash-layout change is introduced.

---

## 22. Downstream compatibility assessment

With this design, later work can proceed without replacing the Batch 11 foundation:

| Later feature | Foundation support |
|---|---|
| SCI persistent Connect/Disconnect | RuntimePort, Controller lifecycle, cancellation token |
| Local app/service preparation | `TaskConnectionRequirement.NONE`, origin-state restoration |
| CPU1/CPU2 separate caches | target key separated from ConnectionInfo; backend cache ownership |
| Advanced Diagnostics | strong request + single/multi-Step Task |
| Advanced Metadata | connected Task + prepared-image payload/caches |
| Advanced Flash | progress preservation, service-internal operation path, cancellation at safe boundaries |
| RUN/RESET | successful `RELEASE_CONNECTION` disposition |
| Receive timeout handling | `ASK_DISCONNECT` and same-Dialog internal cleanup |
| Program workflow | weighted multi-Step plan and persistent session |
| Memory page | read Task requests and structured payloads |
| W5300 transport | RuntimePort/backend boundary; no View change required |

No known architectural blocker remains after the corrections frozen in this document.
