# Phase 11 Batch 8 Memory Layout Correction

This correction supersedes the earlier eight-word Memory table layout.

## Final Memory row layout

```text
Address | +0 | +1 | +2 | +3 | +4 | +5 | +6 | +7 |
        | +8 | +9 | +A | +B | +C | +D | +E | +F
```

Each row represents sixteen 16-bit words. Values that have not been read or are
not supplied by the controller are rendered as `????` rather than an empty cell.
Selecting an unread cell preserves the calculated address and offset while all
value interpretations remain `????`.

The Search field uses the same fixed label width as Start Address, so both input
boxes share the same left edge.

This remains a read-only static view. It does not add memory write operations,
transport access, or controller integration.
