# Documentation Authority Map

This index is the entry point for current documentation. It separates normative authority, implementation guidance, and historical evidence.

## Authority order

1. Explicit user direction for the current change.
2. `architecture/runtime_architecture_contract_v2.md` for shared Runtime V2 architecture.
3. Stable domain contracts: `14_communication_protocol.md`, `13_flash_resident_ram_lib_partition.md`, `03_dsp_bootloader_algorithm.md`, and target/Flash technical guides.
4. `phase_10_8a_pc_operation_library.md` for PC operation semantics.
5. Repository and directory `AGENTS.md` files for contributor boundaries.
6. `phase11_gui_layout_v1_contract.md` for GUI structure and presentation.
7. Usage, release, porting, and hardware-test guides.
8. README summaries and validation records.

A lower level cannot redefine a higher-level contract. Hardware validation records describe observed runs only.

## Current contracts

| Document | Responsibility |
|---|---|
| `architecture/runtime_architecture_contract_v2.md` | Runtime ownership, lifecycle, extensibility, and GUI/runtime boundaries |
| `14_communication_protocol.md` | Framing, payloads, commands, statuses, and protocol reservations |
| `phase_10_8a_pc_operation_library.md` | DSP-touching PC operation APIs and sequencing boundaries |
| `phase_10_8a_operation_library_usage_example.md` | Non-authoritative usage examples for those APIs |
| `phase11_gui_layout_v1_contract.md` | Frozen GUI layout and widget contracts |
| `03_dsp_bootloader_algorithm.md` | DSP bootloader responsibility and algorithm boundaries |
| `13_flash_resident_ram_lib_partition.md` | Flash core/downloaded service partition |
| `27_app_slot_metadata_header_design.md` | Current metadata journal format and semantics |

## Guides and evidence

- `06_device_info_tool.md`, `07_user_porting_guide.md`, `15_ti_sci_flash_kernel_reference_guide.md`, and `16_f28377d_flash_operation_codex_guide.md` are implementation/porting guides.
- `20_phase_6_7_hardware_test_guide.md`, `23_source_run_release_guide.md`, and `24_windows_portable_packaging_guide.md` are operational guides.
- Files under `validation/` preserve scoped evidence; they are not current workflow specifications.
- Both v0.1.0 release-note filenames are retained as release records.

## Capability versus architecture

CPU1 over SCI/RS232 is the currently validated hardware capability. CPU2 and W5300/TCP may remain deferred or disabled. Shared Runtime V2 code nevertheless remains target/profile/capability driven; deferral is not authority to duplicate CPU-specific flows or hardcode CPU1 into shared state, bindings, widgets, or operations.

## History policy

Git history is the archive for completed Phase/Batch plans, evidence handoffs, cleanup notes, superseded requirements, and migration snapshots. Do not add redirect stubs or recreate deleted history documents. New long-lived rules belong in the appropriate current authority above.
