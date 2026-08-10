# GUI AGENTS.md

## Required authority

Before GUI work, read repository `AGENTS.md`, `docs/README.md`, `docs/contracts/runtime_architecture.md`, `docs/contracts/gui_layout.md`, `docs/contracts/pc_operations.md`, and `global_settings.py`. If the change touches protocol or metadata, also read `docs/contracts/communication_protocol.md` or `docs/contracts/metadata_journal.md` respectively.

## GUI boundary

- Use PySide6, not PyQt.
- Layout V1 is the visual authority. Do not redesign its navigation, Ribbon order, pages, TaskDialog, or shared result/console structure.
- `RuntimeBackend` owns runtime state. Views and bindings consume immutable snapshots and emit user intent; they do not own independent business truth.
- DSP-touching actions call `operations/*` through controller/runtime glue with the active `TargetProfile`.
- Widgets do not import or call transports, serial/socket APIs, protocol clients/primitives, command IDs, service attach, target internals, legacy CLI workflows, or Flash/metadata/RUN sequencing.
- Shared bindings and backend logic are target-agnostic. CPU2 may be visible but disabled/unavailable while deferred; do not clone CPU1 logic or hardcode CPU1 defaults into shared widgets.
- Image preparation uses `images/*`; it is separate from DSP operations.
- Verify, IMAGE_VALID, BOOT_ATTEMPT, APP_CONFIRMED, and RUN remain explicit operations. SERVICE_ATTACH is never a public GUI action.
- Normal Program pages expose the workflow defined by the current layout/runtime contracts; do not restore a normal DFU button.

## Presentation and tests

Use the approved theme, token, metric, and semantic icon pipeline. Keep exact visible-state contracts stable and put secondary detail in tooltips/details panels.

GUI tests use static data and injected fakes. They must not open real COM ports, perform autobaud, invoke subprocesses, touch hardware Flash/metadata, send real RUN/reset, or perform CPU2/TCP bring-up.
