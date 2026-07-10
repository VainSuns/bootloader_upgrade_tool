# Phase 11 Batch 5 Program Layout Correction

This correction supersedes the earlier Program-page card placement for Batch 5.

## Final Program layout

```text
ProgramTargetPage
└─ Horizontal splitter 58:42
   ├─ Left workflow pane
   │  ├─ App Image
   │  ├─ Options
   │  └─ Details / Result
   └─ Right state pane
      └─ Status Summary
```

The right Status Summary stretches vertically so its top and bottom align with
the combined three-card stack on the left.

## App Image compact summary

The page keeps the App path selector. The rendered image summary contains only:

```text
Entry point    | Image size
CRC32          | Parse status
```

File name and Target are not rendered. The `file_name` argument remains in the
View setter for future controller compatibility.

## Operation progress

Operation progress remains reserved for a future dedicated dialog owned by GUI
workflow/controller glue. The Program page does not embed progress widgets.
