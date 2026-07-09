# Retired GUI Refactor Workflow

This workflow is retired.

The Phase 11 GUI layout is already frozen.

Do not use this file to generate, redesign, or refactor GUI layout.

This retired workflow is not a runtime guide.

Current Phase 11.1 runtime path is `operations/*` public APIs with active
`TargetProfile` / `CommandSet`.

- bind existing widgets;
- preserve frozen `objectName` values;
- use `images/*` for PC-side file preparation only;
- call `operations/*` public APIs for DSP-touching actions;
- create `OperationContext` / `FlashOperationContext` with active
  `TargetProfile`;
- let operations resolve command ids through `ctx.target.command_set` and
  `require_command()`;
- do not use `gui/program_controller.py` as runtime path;
- do not create CPU1-specific or CPU2-specific duplicated operation flows;
- do not call old CLI / old workflow / old GUI backend as runtime path;
- do not reimplement image parsing, Flash erase/program/verify, metadata writes,
  BOOT_ATTEMPT, APP_CONFIRMED, or RUN sequencing in GUI widgets.

Historical note: older Phase 11 guidance used `headerFrame`, `connectionStrip`,
`bodyFrame`, `bottomConsole`, `Tools / Advanced`, and old form-style
`MainWindow` compatibility wording. Those names are obsolete for current Phase
11 GUI development and may be used only to identify retired guidance.
