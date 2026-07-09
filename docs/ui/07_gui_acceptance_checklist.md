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

- [ ] GUI reuses Phase 10.8A connection/session/operation-library code.
- [ ] CPU1 Load Image / Run uses `ProgramController`.
- [ ] Advanced DSP operations use existing operation-layer flow.
- [ ] GUI does not call subprocess `cpu1_upgrade` CLI.
- [ ] GUI does not directly construct protocol frames.
- [ ] GUI does not directly open serial/socket from widgets.
- [ ] GUI does not duplicate image parsing / Flash / metadata / RUN sequencing.
- [ ] GUI does not expose `SERVICE_ATTACH` as a normal user button.
- [ ] Old CLI / old workflow / old GUI backend files are reference only and not
  runtime path.

## Tests

- [ ] `tests/unit/test_gui_static_layout.py` passes.
- [ ] `tests/unit/test_gui_flash_sectors.py` passes.
- [ ] `tests/unit/gui/test_program_controller.py` passes.
- [ ] New GUI tests cover GUI glue only and do not duplicate operation
  sequencing tests.

## Historical Notes

Older GUI checklist items such as `QFormLayout`, DFU as a normal workflow, and
`tests/unit/test_gui.py` are retired for current Phase 11 integration work.
