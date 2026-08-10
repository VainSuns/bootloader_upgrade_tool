# Product Scope

This project provides a bootloader upgrade path for the TI TMS320F28377D.

## In scope

- A Flash-resident bootloader that owns boot selection, communication recovery, and transfer of control.
- A downloaded Flash Service that performs Flash erase/program/verify work and metadata writes.
- PC command-line and PySide6 GUI workflows built on the same operation library.
- SCI-A over RS232 as the current product transport, with the PC as master and the DSP as slave.
- Application self-confirmation through the metadata journal.
- `RUN_RAM` for development and bring-up workflows.
- Target/profile-driven extension points for additional target resources and transports.

The CPU1 SCI/RS232 product path is currently implemented. CPU2 support is planned but deferred. W5300/TCP is an optional late-stage capability and is also deferred.

## Out of scope or user-owned

- Product-specific board initialization, PLL setup, Flash wait states, DCSM, pump-semaphore handling, and linker placement.
- Bundling TI `hex2000.exe` or TI F021 components without the required external installation and licensing.
- Treating the simulator as a production transport or GUI dependency.
- Fabricating CPU2 behavior from CPU1 defaults while CPU2 resources and firmware are unavailable.

Detailed runtime, wire protocol, DSP, Flash Service, metadata, PC-operation, and GUI rules are defined only by the corresponding documents under [`contracts/`](contracts/). Porting and packaging procedures are under [`guides/`](guides/).
