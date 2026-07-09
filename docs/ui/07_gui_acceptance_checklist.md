# Phase 11 GUI Integration Acceptance Checklist

Use this checklist for current Phase 11 GUI integration PRs.

## Layout

- [ ] `topRibbonShell` exists.
- [ ] Ribbon tabs are `Session` / `Operate` / `View` / `Settings`.
- [ ] `navigationPanel` exists.
- [ ] `pageContentStack` exists.
- [ ] `bottomDock` title is `Console`.
- [ ] Left navigation is `Program / CPU1`, `Program / CPU2`, `Settings`,
  `Memory / CPU1`, `Memory / CPU2`, `Advanced`, `Logs`.
- [ ] Advanced RAM Image has CPU1 and CPU2 image cards.
- [ ] Memory tables are 100 rows x 17 columns.
- [ ] Existing `objectName` values are preserved.

## Function Boundary

- [ ] GUI calls `operations/*` public APIs for all DSP-touching actions.
- [ ] GUI uses `images/*` only for PC-side file preparation / identity
  comparison.
- [ ] GUI creates `OperationContext` / `FlashOperationContext` with active
  `TargetProfile`.
- [ ] Command dispatch is driven by active `TargetProfile.command_set`.
- [ ] GUI does not select command ids directly.
- [ ] GUI does not call `gui/program_controller.py` as runtime path.
- [ ] GUI does not create CPU1-specific or CPU2-specific duplicated operation
  flows.
- [ ] GUI does not call subprocess `cpu1_upgrade` CLI.
- [ ] GUI does not directly construct protocol frames.
- [ ] GUI does not directly call `BootProtocolClient` convenience methods.
- [ ] GUI does not directly open serial/socket from widgets.
- [ ] GUI does not expose `SERVICE_ATTACH` as a normal user button.
- [ ] Old CLI / old workflow / old GUI backend files are reference only and not
  runtime path.

## Tests

- [ ] `tests/unit/test_gui_static_layout.py` passes.
- [ ] `tests/unit/test_gui_flash_sectors.py` passes.
- [ ] `tests/unit/test_phase_10_8a_operations.py` passes.
- [ ] New GUI tests cover GUI glue only and do not duplicate operation
  sequencing tests.

## Historical Notes

Older GUI checklist items such as `QFormLayout`, DFU as a normal workflow, and
`tests/unit/test_gui.py` are retired for current Phase 11 integration work.
