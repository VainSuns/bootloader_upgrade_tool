# Phase 11 GUI Visual Layout Contract

## Status

The current approved and authoritative GUI layout contract is:

```text
docs/phase11_gui_layout_v1_contract.md
```

This file previously described the first single-file static GUI skeleton. That skeleton is no longer the final layout source of truth. It remains a migration reference only.

## Migration Rule

Migration from the former skeleton to the approved V1.0 structure is explicitly allowed. The migration may:

- split `main_window.py` into the approved modular pages and widgets;
- replace `styles.py::APP_QSS` with the approved QSS/token pipeline;
- migrate object names according to the V1.0 object-name mapping;
- introduce the approved splitters and shared panels;
- update GUI tests incrementally.

The implementation must not redesign beyond V1.0, change operation semantics, or connect real hardware during static-layout work.

## Runtime Boundary

The backend/runtime boundary remains unchanged:

```text
GUI widgets
  -> GUI controller / view-model glue
  -> images/* for PC-side preparation only
  -> operations/* public APIs
  -> OperationContext / FlashOperationContext
  -> TargetProfile / CommandSet
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

The GUI must not use subprocess CLI flows, direct protocol construction, direct command-ID selection, direct serial/socket access, or duplicated Flash/metadata/RUN sequencing.
