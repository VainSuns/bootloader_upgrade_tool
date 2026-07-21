# AGENTS.md

## Project rules

This repository implements a DSP28377D bootloader upgrade tool. Before making changes, read:

- `README.md` and `docs/README.md`;
- `docs/architecture/runtime_architecture_contract_v2.md` for Runtime V2;
- `docs/14_communication_protocol.md` for the frozen protocol;
- `docs/phase_10_8a_pc_operation_library.md` and its usage example for DSP-touching PC operations;
- `docs/phase11_gui_layout_v1_contract.md` for GUI layout work;
- the nearest directory-specific `AGENTS.md`.

The user request is the highest authority. RAC-V2 governs shared runtime architecture; stable protocol, DSP, Flash-layout, and operation contracts govern their own technical domains. Guides and evidence records do not override these contracts.

## Stable constraints

- PC is master; DSP is slave.
- The formal protocol is a 16-bit word stream, serialized low byte first.
- SCI `A` autobaud is SerialTransport/connection-layer behavior, not a protocol frame.
- Do not add ACK/NAK words or a generic DSP timeout status.
- Use Program naming, not Download.
- ProgramData/VerifyData are 8-word aligned and PC padding is `0xFFFF`; RamLoadData does not use Flash alignment rules.
- Preserve the Flash-resident core/downloaded service split. The core must not statically link F021 or `flash_service_lib`.
- User-owned low-level initialization, PLL, Flash wait states, raw F021, DCSM, pump semaphore, and linker placement remain user-maintained unless explicitly requested.
- Bootloader reads metadata; downloaded service performs Flash and metadata writes.

## Runtime V2 boundary

```text
GUI -> controller/view-model glue -> operations public APIs
    -> OperationContext/FlashOperationContext -> TargetProfile/CommandSet
    -> UpgradeSession.client.transact() -> protocol -> ByteTransport
```

- `RuntimeBackend` owns runtime truth.
- Shared runtime, bindings, and operations are capability/resource/profile driven, not CPU-name branched.
- Current CPU1-only validation is a capability state, not permission to specialize shared architecture.
- CPU2 may remain disabled or unavailable until its profile, bootloader, resources, and tests exist. Do not fabricate CPU2 behavior, duplicate CPU1 flows, or embed CPU1 defaults in shared components.
- GUI widgets do not access transports, protocol primitives, command IDs, target internals, or operation sequencing.
- `verify_flash_image()` verifies only; `append_image_valid()` is separate.
- `run_flash_app()` sends RUN only; `append_boot_attempt()` is separate.
- SERVICE_ATTACH is internal operation-library behavior.

## Scope and testing

Current validated hardware capability is CPU1 over SCI/RS232. CPU2 runtime and W5300/TCP are deferred. Simulator is a test aid, not a GUI dependency.

GUI tests must not open real ports, autobaud, invoke subprocesses, touch real Flash/metadata/RUN/reset, or perform CPU2/TCP bring-up. Use injected fakes. Do not change frozen protocol behavior without explicit user direction.
