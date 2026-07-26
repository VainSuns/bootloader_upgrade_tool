# DSP28377D Bootloader Upgrade Tool

Windows/PySide6 bootloader upgrade tool for TI TMS320F28377D targets.

## Current capability

The currently validated product path is CPU1 over SCI/RS232. It supports source execution, image preparation, persistent connection/session handling, target discovery, Flash operations through the operation library, metadata operations, RUN, protocol logging, and a simulator test aid.

CPU2 and W5300/TCP remain deferred capabilities. Their deferral does not permit CPU1-specific branching in shared Runtime V2 code: shared runtime, GUI binding, operation dispatch, and state ownership remain target/profile driven.

## Runtime V2 Stage 7A status

Runtime V2 Stage 7A focused software acceptance has passed. This is not a
full-pytest PASS. The validated hardware capability remains CPU1 over
SCI/RS232. The user completed the CPU1 Runtime V2 GUI hardware validation at
the validated HEAD below. The executed procedure and its boundaries are in
[`docs/25_runtime_v2_cpu1_gui_hardware_validation_guide.md`](docs/25_runtime_v2_cpu1_gui_hardware_validation_guide.md),
and the final acceptance evidence is in
[`docs/validation/runtime_v2_cpu1_gui_hw_validation.md`](docs/validation/runtime_v2_cpu1_gui_hw_validation.md).

```text
STAGE_7A_SOFTWARE_GATE = PASS
USER_HARDWARE_VALIDATION_GATE = PASS
CPU1_RUNTIME_V2_GUI_HARDWARE_VALIDATION = PASS
VALIDATED_HEAD = 5834c31e3be9f9e2c1379a075d4478ec22f5d64f
```

```text
Validation date: 2026-07-26
Execution owner: user
Target: TMS320F28377D CPU1
Transport: SCI-A / RS232
Result: PASS
Blocking items: NONE
```

CPU2 and W5300/TCP remain deferred. Program workflow, production Reset, real
periodic Ping, and the final `InstalledResourceProvider` installation layout
also remain deferred.

On the current Windows/PySide6 baseline, full pytest is `NOT RUN`. For the
following two-file Qt/Controller check only,
confirm no earlier repository `.venv` Python process remains, clear
`.pytest_cache` and repository `__pycache__` directories without touching
`.venv`, verify the caches are gone, then use a fresh Python process:

```powershell
.\.venv\Scripts\python.exe -X faulthandler -m pytest `
  tests/unit/test_gui_controller.py `
  tests/unit/test_gui_advanced_metadata_controller.py `
  -q
```

The expected result is `54 passed`. Focused software acceptance is not
equivalent to full pytest PASS. The exact process and cache preflight is in
`AGENTS.md` and the CPU1 hardware-validation guide. These special precautions
do not apply automatically to other targeted test files.

## Quick start

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m bootloader_upgrade_tool
```

If activation is blocked, invoke `.\.venv\Scripts\python.exe` directly.

Image conversion resolves `hex2000.exe` from `pc/config/gui_global_settings.json` first, then from `C2000_CG_ROOT`. Global Settings can override the tool and output paths for the current run.

## Architecture boundaries

- PC is master; DSP is slave.
- The formal protocol is a 16-bit word stream serialized low byte first.
- SCI `A` autobaud belongs to the connection layer, not the framed protocol.
- GUI DSP actions use the operation library and active `TargetProfile`; widgets do not select command IDs or access transports.
- Flash-resident core and downloaded service remain separate. User-owned low-level initialization, raw F021 use, and linker placement remain outside this repository's shared runtime contract.
- Verify and IMAGE_VALID are separate operations. RUN and BOOT_ATTEMPT are separate operations.
- A host timeout is not a general DSP protocol status.

## Documentation

Start at [`docs/README.md`](docs/README.md). Runtime Architecture Contract V2 is the long-term runtime authority; the protocol and operation-library contracts define their respective technical boundaries. Hardware validation records are evidence only, not product workflow authorities.

## Windows portable build

The repository retains the existing one-folder build scripts. `hex2000.exe` is not bundled. See [`docs/24_windows_portable_packaging_guide.md`](docs/24_windows_portable_packaging_guide.md).
