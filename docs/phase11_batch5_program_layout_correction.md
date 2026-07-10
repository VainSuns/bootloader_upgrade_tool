# Phase 11 GUI Layout V1.0 — Batch 5 Approved Correction

## Status

This document is an approved correction to Section 8, **Program Pages**, of
`phase11_gui_layout_v1_contract.md`. Where the two documents differ, this
correction takes precedence until the master V1.0 contract is consolidated.

## Program page hierarchy

CPU1 and CPU2 continue to share:

```text
ProgramTargetPage(target="cpu1" | "cpu2")
```

The corrected hierarchy is:

```text
ProgramTargetPage
├─ pageTitleRow
└─ programBodyScrollArea
   └─ programContentContainer
      └─ programHorizontalSplitter
         ├─ workflowPane
         │  ├─ appImageCard
         │  └─ programOptionsCard
         └─ statePane
            ├─ statusSummaryCard
            └─ detailsResultCard
```

The embedded `operationProgressCard` is removed.

## Corrected metrics

- The horizontal splitter remains non-collapsible with the 58:42 default ratio.
- App Image minimum height is 350 logical pixels so all seven frozen rows remain
  distinct after the application theme is applied.
- Options minimum height remains 82 logical pixels.
- Status Summary minimum height remains 218 logical pixels.
- Details / Result minimum height remains 150 logical pixels and may stretch.

## Progress-dialog contract

Long-running workflow progress is shown in a dedicated dialog, not embedded in
the Program page. The future dialog owns:

```text
Current operation
Stage
Progress
Processed / total
Message
Cancel
```

Cancellation is enabled only while the active workflow stage is safe to cancel.
The Run stage is not cancellable. Phase 11.1 static-layout work does not execute
an operation or display a fake progress dialog.

## Unchanged boundaries

The Program page still does not expose Erase, Program Only, Verify Only,
SERVICE_ATTACH, or an editable Flash-App entry point. Widgets do not open
transports, construct protocol commands, access Flash/metadata, or duplicate the
public PC workflow.
