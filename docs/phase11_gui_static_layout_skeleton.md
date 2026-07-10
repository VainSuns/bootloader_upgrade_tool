# Phase 11 GUI Static Layout Skeleton v6

> **Status: LEGACY MIGRATION BASELINE**
>
> This document described the former single-file static GUI skeleton. It is no longer the final Phase 11 layout contract.
>
> The authoritative contract is:
>
> ```text
> docs/phase11_gui_layout_v1_contract.md
> ```
>
> The old implementation, object names, dimensions, and tests may be used to identify migration impact, but they must not override the approved V1.0 structure. Historical details remain available in Git history at the commit that introduced and maintained Static Layout Skeleton v6.

## Legacy Scope Summary

The former skeleton contained:

```text
MainWindow single-file layout
Ribbon tabs and groups
Navigation tree
Program CPU1 / CPU2 pages
separate Session Settings and Global Settings pages
Advanced page and internal tabs
Memory CPU1 / CPU2 tables
Logs page
fixed-height bottomDock Console
legacy objectName values
legacy styles.py constants and APP_QSS
```

It intentionally did not implement serial transport, autobaud, real COM connection, Flash operations, metadata writes, RAM operations, memory reading, operation-library wiring, or hardware validation.

## Migration Use

Use the former source and tests only to:

- preserve valid Session/Operate content semantics;
- identify compatibility entry points;
- identify fields that must be represented in the V1.0 pages;
- migrate each page incrementally without touching backend behavior.

Do not use this legacy document to reject the approved modular migration.

## Runtime and Hardware Boundary

The old skeleton's no-hardware boundary remains valid. Static GUI work must not open serial ports, execute autobaud, call subprocess, perform Flash or metadata operations, send RUN/reset, or perform CPU2/W5300 bring-up.

Future runtime integration must use the operation-library path defined in `docs/phase11_gui_layout_v1_contract.md` and the Phase 10.8A operation documents.
