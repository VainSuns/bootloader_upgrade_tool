# AGENTS.md

## Project Rules

This repository implements a DSP28377D bootloader upgrade tool.

Before editing code, read:

* `README.md`
* `docs/01_mvp_requirements.md`
* `docs/02_architecture_constraints.md`
* `docs/03_dsp_bootloader_algorithm.md`
* `docs/04_pc_gui_requirements.md`
* `docs/11_codex_task_list.md`
* `docs/12_mvp_acceptance_criteria.md`
* `docs/13_flash_resident_ram_lib_partition.md`
* `docs/14_communication_protocol.md`
* `docs/16_f28377d_flash_operation_codex_guide.md`

Before Phase 11 GUI work, also read:

* `docs/phase11_gui_layout_v1_contract.md`
* `docs/phase11_gui_mvp_requirements.md`
* `docs/phase_10_8a_operation_library_usage_example.md`
* `docs/phase_10_8a_pc_operation_library.md`
* `pc/src/bootloader_upgrade_tool/gui/global_settings.py`

The following files describe the former static-layout implementation and are migration references only:

* `docs/phase11_gui_static_layout_skeleton.md`
* `tests/unit/test_gui_static_layout.py`
* `pc/src/bootloader_upgrade_tool/gui/main_window.py`
* `pc/src/bootloader_upgrade_tool/gui/styles.py`

## Hard Constraints

* DSP is always slave. PC GUI is always master.
* Formal protocol is a 16-bit word stream.
* SCI `'A'` autobaud is SerialTransport / connection-layer behavior, not a protocol frame.
* Do not use ACK/NAK word protocol.
* Do not add timeout as a DSP protocol status code.
* Use Program naming, not Download.
* Phase 11 GUI must not expose DFU as a normal GUI flow or button.
* ProgramData / VerifyData data must be 8-word aligned; RamLoadData is RAM and must not use Flash alignment rules.
* PC pads Flash write data with `0xFFFF`.
* Preserve the Flash-resident core / downloaded RAM service-library split.
* Do not implement low-level DSP system init, PLL, Flash wait-state, raw F021 API, DCSM, pump semaphore, or linker placement unless explicitly requested.
* Do not modify user-owned DSP initialization or linker files during GUI work.
* Flash-resident bootloader must not statically link F021 or flash_service_lib.
* Bootloader reads metadata only. Downloaded flash_lib performs erase/program/verify and metadata writes.
* CPU1 functionality is completed before CPU2 adaptation.
* W5300/TCP is optional and last.

## Phase 11 GUI Runtime Path

The only supported DSP-touching GUI path is:

```text
GUI widgets
  -> GUI controller / view-model glue
  -> images/* for PC-side file preparation only
  -> operations/* public APIs for DSP-touching actions
  -> OperationContext / FlashOperationContext
  -> active TargetProfile / CommandSet
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

Rules:

* All DSP-touching GUI actions call `operations/*` public APIs.
* The GUI creates `OperationContext` / `FlashOperationContext` with the active `TargetProfile`.
* Command dispatch is driven by `TargetProfile.command_set`; the GUI never selects command IDs directly.
* Do not use `gui/program_controller.py` as the Phase 11 runtime path.
* Do not duplicate CPU1- and CPU2-specific operation flows.
* Do not call `cpu1_upgrade` through subprocess.
* Widgets must not directly use pySerial, sockets, Simulator internals, protocol primitives, or BootProtocolClient convenience calls.
* Widgets must not reimplement image parsing, Flash erase/program/verify, metadata writes, BOOT_ATTEMPT, APP_CONFIRMED, or RUN sequencing.
* `verify_flash_image()` verifies only; `append_image_valid()` writes IMAGE_VALID separately.
* `run_flash_app()` sends RUN only; `append_boot_attempt()` writes BOOT_ATTEMPT separately.
* SERVICE_ATTACH is internal operation-library behavior and is not a public GUI action.

## Phase 11 GUI Layout Contract

The approved final layout contract is:

* `docs/phase11_gui_layout_v1_contract.md`

The former single-file static skeleton is a migration baseline, not the final layout source of truth. Migration to the approved modular V1.0 structure is explicitly allowed.

Allowed during the approved migration:

* split `main_window.py` into the documented pages and widgets modules;
* replace `styles.py::APP_QSS` with the approved theme pipeline;
* migrate object names according to the explicit V1.0 mapping;
* add the approved splitters, scoped Settings page, Advanced shared result panel, Memory details pane, Logs details pane, and global Console;
* update static layout tests incrementally as each component is migrated.

Not allowed:

* redesigning beyond the approved V1.0 contract;
* changing the Ribbon tab order or left-navigation structure;
* inventing new normal operation flows;
* changing operation semantics or protocol contracts;
* connecting real hardware during static-layout implementation;
* deleting CPU2 or TCP placeholders from the review layout.

## MVP Scope

MVP supports:

* Windows Python 3.12 and PySide6 source execution;
* SCI/RS232;
* CPU1 App only;
* `.out -> hex2000 -boot -a -sci8`;
* `pc/config/gui_global_settings.json` `hex2000.executable_path`, then `C2000_CG_ROOT` based hex2000 lookup;
* device_info generated from linker `.cmd` MEMORY;
* Phase 11 normal workflow: Load Image and Run only.

Simulator remains a backend test aid where already present; it is not a GUI dependency.

## Future Only

Do not implement unless explicitly requested:

* W5300/TCP runtime support;
* CPU2 upgrade runtime support;
* App Upload / Readback;
* RAM service-lib actual loading;
* DCSM Unlock;
* encryption/signature/compression;
* installer or packaging changes.

## Phase 11 GUI Test Boundaries

GUI tests must not open real COM ports, perform real autobaud, call subprocess, or execute real Flash, metadata, RUN, reset, W5300, or CPU2 operations. Use static preview data, injected fakes, and mock dependencies.

## Development Baseline

* Use 64-bit Python 3.12.x.
* Use PySide6, not PyQt.
* MVP runs from source; packaging is future work.
* Keep protocol, firmware parsing, operations, session, transport, and GUI concerns separate.
* Do not edit frozen protocol behavior without explicit user direction.
