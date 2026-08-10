# AGENTS.md

## Project rules

This repository implements a DSP28377D bootloader upgrade tool. Before making changes, read `README.md`, `docs/README.md`, `docs/product_scope.md`, and the nearest directory-specific `AGENTS.md`. Then read only the authority for the current modification domain:

- Runtime and GUI application architecture: `docs/contracts/runtime_architecture.md`;
- protocol: `docs/contracts/communication_protocol.md`;
- DSP bootloader: `docs/contracts/dsp_bootloader.md`;
- downloaded Flash Service: `docs/contracts/flash_service.md`;
- metadata: `docs/contracts/metadata_journal.md`;
- PC operations: `docs/contracts/pc_operations.md`;
- GUI layout: `docs/contracts/gui_layout.md`;
- F28377D porting, linker, and F021 integration: `docs/guides/f28377d_porting.md`.

The user request is the highest authority. Each domain contract is the sole long-term authority for its subject; guides and README summaries do not override contracts.

## Stable constraints

- PC is master; DSP is slave.
- The formal protocol is a 16-bit word stream, serialized low byte first.
- SCI `A` autobaud is SerialTransport/connection-layer behavior, not a protocol frame.
- Do not add ACK/NAK words or a generic DSP timeout status.
- Use Program naming, not Download.
- ProgramData/VerifyData are 8-word aligned and PC padding is `0xFFFF`; RamLoadData does not use Flash alignment rules.
- Preserve the Flash-resident core/downloaded service split. The core must not statically link F021 or `flash_service_lib`.
- User-owned low-level initialization, PLL, Flash wait states, raw F021, DCSM, pump semaphore, and linker placement remain user-maintained unless explicitly requested.
- Project-adapted or size-minimized replacements for TI device-support sources must live under the owning `bootloader_user` layer, use `BootUser_` symbols, and preserve upstream license attribution. Do not place such project-specific implementations under `dsp/device_support`.
- Bootloader reads metadata; downloaded service performs Flash and metadata writes.

## Runtime V2 boundary

```text
GUI -> controller/view-model glue -> operations public APIs
    -> OperationContext/FlashOperationContext -> TargetProfile/CommandSet
    -> UpgradeSession.client.transact() -> protocol -> ByteTransport
```

- `RuntimeBackend` owns runtime truth.
- Shared runtime, bindings, and operations are capability/resource/profile driven, not CPU-name branched.
- Current CPU1-only support is a capability state, not permission to specialize shared architecture.
- CPU2 may remain disabled or unavailable until its profile, bootloader, resources, and tests exist. Do not fabricate CPU2 behavior, duplicate CPU1 flows, or embed CPU1 defaults in shared components.
- GUI widgets do not access transports, protocol primitives, command IDs, target internals, or operation sequencing.
- `verify_flash_image()` verifies only; `append_image_valid()` is separate.
- `run_flash_app()` sends RUN only; `append_boot_attempt()` is separate.
- SERVICE_ATTACH is internal operation-library behavior.

## Scope and testing

Current supported hardware capability is CPU1 over SCI/RS232. CPU2 runtime and W5300/TCP are deferred. Simulator is a test aid, not a GUI dependency.

GUI tests must not open real ports, autobaud, invoke subprocesses, touch real Flash/metadata/RUN/reset, or perform CPU2/TCP bring-up. Use injected fakes. Do not change frozen protocol behavior without explicit user direction.

### Windows/PySide6 targeted Qt/Controller procedure

For the current Windows/PySide6 environment, do not default to a full-repository
pytest collection. Do not delete, skip, or xfail the cancellation tests, and do
not change business contracts in response to a native full-collection crash.

Only when running the two files below, first verify that no earlier repository
virtual-environment Python process remains. An interrupted or timed-out process
must exit before a new run starts. Then clear repository caches outside
`.venv` and verify none remain:

```powershell
$repoPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
$repoPythonProcesses = @(
    Get-Process python, pythonw -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $repoPython }
)
if ($repoPythonProcesses.Count -ne 0) {
    $repoPythonProcesses | Select-Object Id, ProcessName, Path, StartTime
    throw "A previous repository Python process is still running"
}

$repoRoot = (Get-Item -LiteralPath .).FullName.TrimEnd('\')
$venvRoot = (Get-Item -LiteralPath .venv).FullName.TrimEnd('\')
$cacheDirs = @(
    Get-ChildItem -LiteralPath $repoRoot -Recurse -Directory -Force |
        Where-Object {
            $_.Name -in @('.pytest_cache', '__pycache__') -and
            -not $_.FullName.StartsWith(
                $venvRoot + '\',
                [System.StringComparison]::OrdinalIgnoreCase
            )
        }
)
$cacheDirs | Remove-Item -Recurse -Force

$remainingCaches = @(
    Get-ChildItem -LiteralPath $repoRoot -Recurse -Directory -Force |
        Where-Object {
            $_.Name -in @('.pytest_cache', '__pycache__') -and
            -not $_.FullName.StartsWith(
                $venvRoot + '\',
                [System.StringComparison]::OrdinalIgnoreCase
            )
        }
)
if ($remainingCaches.Count -ne 0) {
    $remainingCaches.FullName
    throw "Repository test caches remain"
}

$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONFAULTHANDLER = "1"

.\.venv\Scripts\python.exe -X faulthandler -m pytest `
  tests/unit/test_gui_controller.py `
  tests/unit/test_gui_advanced_metadata_controller.py `
  -q
```

Pytest must exit successfully and all selected tests must pass. Each change must run focused tests directly related to its changed files, contracts, and runtime behavior. These two Qt/Controller files are a targeted procedure, not a permanent product authority, and do not replace feature-specific focused tests. Never
describe an unrun full pytest collection as a full-suite PASS. Reassess this
policy separately when Python, PySide6, pytest, or the test infrastructure
changes. For repeated stability
runs, invoke the pytest command again only after the previous process has
exited and the repository process check again reports zero. This process/cache
procedure is specific to `test_gui_controller.py` and
`test_gui_advanced_metadata_controller.py`; do not impose it on unrelated
targeted tests unless a task explicitly requires it.
