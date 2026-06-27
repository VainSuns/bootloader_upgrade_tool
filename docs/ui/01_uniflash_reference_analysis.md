# UniFlash Reference Analysis

This project may use UniFlash-like information architecture as a reference, not
as a visual asset source.

## Useful Patterns

1. A top application bar gives the tool name, connection state, and global
   settings entry.
2. A left navigation sidebar separates tasks instead of placing every field in
   one form.
3. The main area groups controls by user task: device, firmware, operation,
   memory, logs, and settings.
4. Program operations are visually stronger than secondary diagnostics.
5. Settings and advanced memory controls are not mixed into the default program
   workflow.
6. A persistent console at the bottom makes progress and failures visible during
   long operations.
7. Status badges and button hierarchy make it clear whether the target is
   disconnected, connected, busy, failed, or complete.

## Local Mapping

| Reference concept | Bootloader Upgrade Tool mapping |
|---|---|
| Program page | Operation page |
| Target connection | Target Device card |
| Image selection | Firmware Image card |
| Console | Bottom Console panel |
| Settings | Settings page |
| Memory tools | Memory page, future RAM/Flash diagnostics |

## Boundaries

- Do not use TI logos, icons, wording that implies TI ownership, or copied
  screenshots.
- Do not introduce Electron, React, Flutter, Qt Designer, or another GUI
  framework.
- Do not hide the project-specific protocol and Flash constraints behind a
  generic programmer UI.
