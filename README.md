# DSP28377D Bootloader Upgrade Tool

Windows/PySide6 bootloader upgrade tool for TI TMS320F28377D targets.

## Current capability

The currently validated product path is CPU1 over SCI/RS232. It supports source execution, image preparation, persistent connection/session handling, target discovery, Flash operations through the operation library, metadata operations, RUN, protocol logging, and a simulator test aid.

CPU2 and W5300/TCP remain deferred capabilities. Their deferral does not permit CPU1-specific branching in shared Runtime V2 code: shared runtime, GUI binding, operation dispatch, and state ownership remain target/profile driven.

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
