# Phase 11 Batch 8 Validation — Memory and Logs

## Scope

Batch 8 replaces the CPU1 Memory, CPU2 Memory, and Logs placeholders with static
read-only pages.  No operation/session/transport/protocol backend is imported or
invoked.

## Memory contract

- One shared `MemoryTargetPage(target="cpu1" | "cpu2")` implementation.
- Controls: Start Address, Word Count, Display Format, Search, Refresh, Export.
- Word Count default 256 and UI range 1..4096.
- Formats: Hex16, Unsigned, Signed, ASCII.
- Table: Address plus +0..+7, eight 16-bit words per row.
- Table is read-only; no write/modify/commit/patch/fill controls.
- Search filters only currently loaded local rows.
- Details: Address, Offset, Hex16, Unsigned, Signed, ASCII, Copy.
- Preview data is explicitly labelled.
- CPU2 page is visible for layout review and target controls are disabled.

## Logs contract

- Structured Logs page is separate from the global Console.
- Filters: Level, Source, Search, Reset Filter, Export, Open Folder, Clear Logs.
- Level choices: All, Debug, Info, Warning, Error, Success, Protocol.
- Table columns: Time, Level, Source, Operation, Message.
- Stage is shown only in the details pane.
- Export and Open Folder remain disabled until controller/file integration.
- Clear Logs clears only the local Logs table and never touches Console.
- Preview rows are explicitly labelled.

## Prohibited runtime behavior

Batch 8 does not:

- connect SCI or TCP;
- read or write target memory;
- open or export log files;
- call operations or protocol clients;
- write Flash or metadata;
- implement CPU2 or W5300 runtime behavior.

## Validation

```powershell
$env:QT_QPA_PLATFORM = "offscreen"

python -m pytest `
  .\tests\unit\test_gui_memory_pages.py `
  .\tests\unit\test_gui_logs_page.py `
  .\tests\unit\test_gui_static_layout.py `
  .\tests\unit\test_gui_view_import_boundaries.py `
  .\tests\unit\test_gui_navigation.py `
  .\tests\unit\test_gui_ribbon.py `
  .\tests\unit\test_gui_theme_contract.py `
  -q
```
