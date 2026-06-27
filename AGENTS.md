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

## Hard Constraints

* DSP is always slave. PC GUI is always master.
* Formal protocol is 16-bit word stream.
* SCI `'A'` autobaud handshake is IO Device connection layer, not protocol frame.
* Do not use ACK/NAK word protocol.
* Do not add timeout as a DSP protocol status code.
* Use Program naming, not Download.
* DFU is GUI flow: Erase + Program + Verify.
* ProgramData / VerifyData data must be 8-word aligned; RamLoadData is RAM and must not use Flash alignment rules.
* PC pads write data with `0xFFFF`.
* Flash/RAM write details must preserve the Flash-resident core / RAM-resident service lib split.
* Codex must not implement low-level DSP system init, PLL, Flash wait-state, raw F021 API, DCSM, pump semaphore, or linker placement.
* Codex should generate user-port templates only for hardware-dependent DSP code.
* PC GUI flow must use the IO Device abstraction; it must not directly depend on pySerial or sockets.

## MVP Scope

MVP supports:

* Windows Python + PySide6 GUI source execution;
* SCI/RS232;
* Simulator;
* CPU1 App only;
* `.out -> hex2000 -boot -a -sci8`;
* `C200_CG_ROOT` based hex2000 lookup with manual fallback;
* device_info generated from linker `.cmd` MEMORY;
* Ping / GetDeviceInfo / Erase / Program / Verify / Run / Reset.

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

## Development Baseline

* Use 64-bit Python 3.12.x.
* Use PySide6, not PyQt.
* MVP runs from source; packaging is future work.
* Keep protocol, firmware parsing, IO devices, and GUI concerns in separate modules.
* Do not edit frozen protocol behavior without explicit user direction.
