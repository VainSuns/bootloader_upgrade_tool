# Retired GUI Refactor Workflow

This workflow is retired.

The Phase 11 GUI layout is already frozen.

Do not use this file to generate, redesign, or refactor GUI layout.

Current work is GUI integration only:

- bind existing widgets;
- preserve frozen `objectName` values;
- reuse Phase 10.8A operation flow;
- use `ProgramController` for CPU1 Load Image / Run;
- use existing operation-layer flow for Advanced DSP operations;
- do not call old CLI / old workflow / old GUI backend as runtime path;
- do not reimplement image parsing, Flash erase/program/verify, metadata writes,
  BOOT_ATTEMPT, APP_CONFIRMED, or RUN sequencing in GUI widgets.

Historical note: older Phase 11 guidance used `headerFrame`, `connectionStrip`,
`bodyFrame`, `bottomConsole`, `Tools / Advanced`, and old form-style
`MainWindow` compatibility wording. Those names are obsolete for current Phase
11 GUI development and may be used only to identify retired guidance.
