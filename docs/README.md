# Documentation Index

Each technical fact has one long-term authority. When documents conflict, use this order:

1. The user's explicit decision for the current work.
2. [Product scope](product_scope.md).
3. Domain documents under [`contracts/`](contracts/).
4. Procedures under [`guides/`](guides/).
5. The repository [README](../README.md).
6. Historical release notes under [`releases/`](releases/).

## Contracts

| Document | Authority |
|---|---|
| [Runtime architecture](contracts/runtime_architecture.md) | Runtime ownership, lifecycle, events, policies, evidence, and dependency direction |
| [Communication protocol](contracts/communication_protocol.md) | Wire serialization, frames, CRC, commands, payloads, status, and compatibility |
| [DSP bootloader](contracts/dsp_bootloader.md) | Bootloader algorithm, IO/action boundaries, timeout recovery, and automatic-boot decision |
| [Flash Service](contracts/flash_service.md) | Flash-core/service split, descriptor/ABI attachment, and Flash/metadata write ownership |
| [Metadata journal](contracts/metadata_journal.md) | Metadata layout, records, binding, scanning, and power-loss publication |
| [PC operations](contracts/pc_operations.md) | Public operation semantics, sequencing, cancellation, and admission |
| [CLI](contracts/cli.md) | Formal CLI command surface, output, confirmation, shell and lifecycle semantics |
| [GUI layout](contracts/gui_layout.md) | Frozen window/widget hierarchy, object names, dimensions, navigation, and presentation |

## Guides and releases

- [F28377D porting](guides/f28377d_porting.md) covers the user-maintained device, linker, F021, and generated-profile boundary.
- [Windows portable build](guides/windows_portable_build.md) covers packaging and launch.
- [v0.1.0 release notes](releases/v0.1.0.md) record the formal release history.

Git history contains obsolete Phase, Batch, migration, handoff, and validation records. Those records are not current authorities.
