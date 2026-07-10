# Phase 11 Batch 8 Memory Alignment Correction

This correction refines the approved 16-word Memory layout.

- The top read-control row is packed from the left; unused width remains at the right.
- Search remains aligned with the Start Address editor.
- Address column width is 92 logical pixels.
- Each word column width is 48 logical pixels.
- The default Memory/Selected Word splitter ratio is 82:18.
- Selected Word minimum width is 220 logical pixels.
- The details label column is reduced while preserving complete values.

No target read, write, export, transport, or operation behavior is added.

## Final width refinement

- Memory Words / Selected Word default splitter ratio: `86:14`.
- Selected Word minimum width: `190 px`.
- Each of the sixteen word columns: `52 px`.
- Address column remains `92 px`.


## Final width refinement

- Selected Word no longer has an artificial minimum width; Qt content size is the lower bound.
- The redundant Selected Word subtitle is removed and detail labels use a compact 64 px width.
- The default splitter ratio is 90:10.
- Each word column is 58 px so four hexadecimal digits are less likely to be elided.
