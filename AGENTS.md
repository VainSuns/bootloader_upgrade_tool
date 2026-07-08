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

* `docs/phase11_gui_visual_layout_contract.md`
* `docs/phase11_gui_mvp_requirements.md`
* `docs/phase_10_8a_operation_library_usage_example.md`
* `pc/src/bootloader_upgrade_tool/gui/global_settings.py`
* `pc/src/bootloader_upgrade_tool/gui/program_controller.py`

## Hard Constraints

* DSP is always slave. PC GUI is always master.
* Formal protocol is 16-bit word stream.
* SCI `'A'` autobaud handshake is IO Device connection layer, not protocol frame.
* Do not use ACK/NAK word protocol.
* Do not add timeout as a DSP protocol status code.
* Use Program naming, not Download.
* Phase 11 GUI must not expose DFU as a normal GUI flow or button. The old "DFU = Erase + Program + Verify" GUI guidance is obsolete.
* ProgramData / VerifyData data must be 8-word aligned; RamLoadData is RAM and must not use Flash alignment rules.
* PC pads write data with `0xFFFF`.
* Flash/RAM write details must preserve the Flash-resident core / RAM-resident service lib split.
* Codex must not implement low-level DSP system init, PLL, Flash wait-state, raw F021 API, DCSM, pump semaphore, or linker placement.
* Codex should generate user-port templates only for hardware-dependent DSP code.
* Phase 11 GUI runtime path is: GUI widgets -> GUI controller -> operations/* -> UpgradeSession.client.transact() -> BootProtocolClient / FrameReader -> ByteTransport.
* Old guidance that GUI must call workflow / IO Device layers directly is obsolete. GUI widgets must not directly depend on pySerial, sockets, Simulator internals, protocol primitives, or old workflow/CLI layers.

## Phase 11 GUI Contract

* `MainWindow` central widget top-level order is exactly: `headerFrame`, `connectionStrip`, `bodyFrame`, `bottomConsole`.
* `connectionStrip` is a direct top-level child below `headerFrame` and above `bodyFrame`; it is not inside CPU1 page, `pageStack`, a scroll area, a card, or a `QGroupBox`.
* `connectionStrip` contains Port, Baud, one stateful connection button, and Status. It has no separate Disconnect button and no timeout fields.
* Navigation is exactly: Program / CPU1, Tools / Advanced, Logs, Settings.
* CPU1 page title is `CPU1 Program`.
* CPU1 page sections are: App Image, Options, Operations, Status Summary.
* Normal operation buttons are only: Load Image, Run.
* Confirm App, Auto Run after Load, and Force Load are checkboxes under Options, not buttons.
* `SERVICE_ATTACH` must not be exposed as a public GUI action.
* `verify_flash_image()` does not write `IMAGE_VALID`; `append_image_valid()` writes `IMAGE_VALID` separately.
* `run_flash_app()` does not write `BOOT_ATTEMPT`; `append_boot_attempt()` writes `BOOT_ATTEMPT` separately.
* Operation page, Firmware page, Erase, Program, Verify, DFU, and Simulator-dependent GUI workflows are obsolete for Phase 11 normal GUI work.
* Old `MainWindow` compatibility attributes are temporary compatibility only. Do not use them to justify expanding the old form-style UI.

## MVP Scope

MVP supports:

* Windows Python + PySide6 GUI source execution;
* SCI/RS232;
* CPU1 App only;
* `.out -> hex2000 -boot -a -sci8`;
* `C200_CG_ROOT` based hex2000 lookup with manual fallback;
* device_info generated from linker `.cmd` MEMORY;
* Phase 11 GUI normal workflow: Load Image and Run only.
* Simulator remains a non-GUI/backend test aid where already present; it is not a Phase 11 GUI dependency.

## Future Only

Do not implement unless explicitly requested:

* W5300/TCP;
* CPU2 upgrade;
* App Metadata;
* App Upload / Readback;
* RAM service lib actual loading;
* DCSM Unlock;
* encryption/signature/compression;
* CLI;
* installer.

## Phase 11 GUI Test Boundaries

GUI tests must not open real COM ports, perform real autobaud, call subprocess, or execute real Flash, metadata, RUN, reset, W5300, or CPU2 actions. Use fake session factories and fake dependencies.

## Development Baseline

* Use 64-bit Python 3.12.x.
* Use PySide6, not PyQt.
* MVP runs from source; packaging is future work.
* Keep protocol, firmware parsing, IO devices, and GUI concerns in separate modules.
* Do not edit frozen protocol behavior without explicit user direction.
