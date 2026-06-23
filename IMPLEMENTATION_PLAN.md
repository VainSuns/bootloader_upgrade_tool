# Implementation Plan: Phases 0-2

This plan maps `docs/11_codex_task_list.md` to the first implementation milestones. Later phases are intentionally out of scope.

## Milestone 0: Repository baseline

Tasks: `DOC-001`, `DOC-002`, `REPO-001`.

- Keep the existing documentation as the source of truth.
- Establish the `pc/`, `dsp/`, `tools/`, `examples/`, and `tests/` boundaries.
- Configure a Python 3.12 source-layout package with PySide6 reserved for later GUI work.
- Preserve separate DSP `core/` and `service_flash/` directories without implementing hardware-dependent code.

Exit criteria: the package imports, the scaffold test passes, and no GUI, transport, DSP Flash, or business-command behavior exists.

## Milestone 1: File parsing

Tasks: `PC-001` through `PC-005`, `TEST-001`.

- Parse linker `.cmd` `MEMORY` declarations and generate validated `device_info.json`.
- Locate `hex2000` through `C200_CG_ROOT`, while allowing an explicit fallback path.
- invoke `hex2000 -boot -a -sci8`, parse its output, and build an immutable `FirmwareImage` model.
- Cover valid input, malformed input, address ranges, entry points, and conversion failures with unit tests.

Exit criteria: deterministic parser fixtures produce the expected device information and firmware model without importing GUI or IO Device code.

## Milestone 2: Protocol core

Tasks: `PROTO-001` through `PROTO-006`.

- Add protocol constants directly from `docs/14_communication_protocol.md`.
- Implement and test CRC-16/CCITT-FALSE over the little-endian byte stream.
- Add frame encode/decode, bounded resynchronization, and `DeviceInfo` / `ErrorDetail` models.
- Enforce non-empty, maximum-sized, 8-word-aligned write payloads; PC padding uses `0xFFFF`.

Exit criteria: golden vectors cover CRC, framing, sequence handling, resync, model decoding, and alignment validation. No protocol business-command workflows are added.

## Next boundary

Phase 3 starts only after these milestones pass. It introduces the IO Device abstraction, Simulator/Serial adapters, and PySide6 GUI flow; those are not part of this scaffold.

