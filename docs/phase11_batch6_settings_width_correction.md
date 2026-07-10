# Phase 11 Batch 6 Settings Width Correction

## Purpose

Remove the centered maximum-width wrapper from the Settings page so the page
uses the available workspace width at large window sizes.

## Corrected layout

```text
SettingsPage
├─ PageHeader
└─ settingsContentContainer (horizontal expanding)
   ├─ settingsScopeTabs (compact, left aligned)
   └─ settingsContentStack
      └─ scope splitter
         ├─ fixed-width category list
         └─ expanding category content
```

## Behavior

- The Settings content container has no page-specific maximum width.
- The category list remains constrained by the existing minimum/maximum metrics.
- The category content and action bar expand into the remaining page width.
- Current/Global tabs remain compact instead of stretching across the page.
- No settings persistence, COM scan, transport open, operation call, or hardware
  behavior is introduced.
