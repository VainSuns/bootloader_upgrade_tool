# Phase 11 GUI Visual Layout Contract

Project: `bootloader_upgrade_tool`  
Target: TMS320F28377D CPU1  
GUI stack: PySide6  
Purpose: executable visual/layout contract for Phase 11 GUI work

This document converts the supplied GUI/reference screenshots into concrete UI rules for Codex. It is intentionally prescriptive so that Codex does not freely redesign the application.

---

## 1. Design Intent

The Phase 11 GUI should look like an engineering upgrade utility, not a demo form.

Use the reference screenshots as guidance for:

- persistent application shell
- compact top status/connection area
- left navigation rail
- card/accordion based content areas
- bottom console/log drawer
- clear separation between normal workflow and advanced/debug operations

Do not copy vendor logos, product names, icons, or exact branding. Use project-specific naming and a neutral professional style.

---

## 2. Global Application Shell

### 2.1 Window

Recommended development size:

```text
Default: 1360 x 900
Minimum: 1180 x 760
```

The GUI must remain usable when resized. Avoid absolute-position layouts except for small icon/button alignment inside fixed-height bars.

### 2.2 Top Header

A persistent top header must span the full width.

Required contents:

```text
Left:
  DSP28377D Bootloader Upgrade Tool

Right:
  connection status indicator
  connection status text
  Settings button
```

Header style:

```text
height: 40-48 px
background: dark navy / dark blue project color
text: white or near-white
status indicator: small circular dot
```

Status examples:

```text
Disconnected
Connecting...
Connected
Busy
Error
```

Do not put detailed timeout fields in the header.

---

## 3. Main Layout

The main window uses four persistent regions:

```text
+----------------------------------------------------------+
| Top Header                                               |
+-------------+--------------------------------------------+
| Left Nav    | Main Content                               |
|             |                                            |
|             |                                            |
+-------------+--------------------------------------------+
| Bottom Console / Log Drawer                              |
+----------------------------------------------------------+
```

### 3.1 Left Navigation Rail

Width:

```text
160-190 px
```

Required Phase 11 navigation items:

```text
CPU1 Program
Advanced
Logs
Settings
```

Optional disabled/skeleton items may exist only if clearly disabled:

```text
CPU2
Network
```

Do not expose disabled items as usable actions.

Navigation style:

```text
selected item: light highlight background + left accent bar
normal item: flat text row
hover item: subtle background change
```

The selected page must be obvious.

### 3.2 Main Content Region

The main content region must use cards and grouped sections. Avoid placing controls directly on a blank canvas.

Card style:

```text
background: white or very light gray
border: 1 px light gray
corner radius: small, optional
padding: 12-16 px
spacing between cards: 10-14 px
```

Section title style:

```text
font weight: bold
font size: 13-14 px
```

Avoid dense, full-width text blocks. Prefer labeled rows and compact summaries.

### 3.3 Bottom Console / Log Drawer

A bottom drawer must be available on all pages.

Collapsed height:

```text
28-36 px
```

Expanded height:

```text
180-260 px
```

Required controls:

```text
Console title
Clear
Save Log
Collapse / Expand
```

Recommended log columns or formatted lines:

```text
time | level | operation step | message
```

The console must not hide the main action buttons permanently. It may overlay or resize the content area, but action buttons must remain reachable.

---

## 4. Connection Ribbon

The Connection Ribbon belongs near the top of the main content area, under the header. It is not a settings page replacement.

Required fields:

```text
Port dropdown
Baud dropdown
Connect / Disconnect button
Connection status text
```

Do not show these fields in the ribbon:

```text
TX timeout
RX timeout
autobaud timeout
flash service path
hex2000 path
temporary directory
```

Those belong in Global Settings.

Behavior:

```text
Disconnected:
  Port and Baud editable
  Connect enabled
  Disconnect hidden or disabled

Connecting:
  Port and Baud disabled
  Connect disabled
  status = Connecting...

Connected:
  Port and Baud disabled
  Connect replaced by Disconnect
  status = Connected

Busy:
  Disconnect disabled unless safe
  action buttons disabled according to operation state
```

---

## 5. CPU1 Program Page

This is the normal user workflow page. It must be simple and should not expose low-level protocol details.

### 5.1 Required Sections

Use these cards in order:

```text
1. Connection Ribbon
2. Firmware Image
3. Load / Run Options
4. Actions
5. Target / Metadata Summary
6. Progress / Result Summary
```

### 5.2 Firmware Image Card

Required controls:

```text
App image path text field
Browse button
Firmware summary area
```

Firmware summary should show, when available:

```text
entry point
image size words
image CRC32
app end
source file name
```

Before an image is selected, show a neutral placeholder such as:

```text
No firmware image selected.
```

### 5.3 Load / Run Options Card

Required checkboxes:

```text
Force Load
Auto Run after Load
Confirm App
```

Rules:

```text
Force Load:
  affects Load Image only

Auto Run after Load:
  if checked, Run button is disabled
  Load Image performs Load sequence, then Run sequence after IMAGE_VALID succeeds

Confirm App:
  Run option only
  not a standalone action
  if enabled, APP_CONFIRMED must be written before RUN
```

### 5.4 Actions Card

The CPU1 normal page must have exactly two main workflow buttons:

```text
Load Image
Run
```

Button rules:

```text
Load Image:
  primary action for image write flow

Run:
  starts the currently valid App
  disabled when Auto Run after Load is checked
```

Do not add these as normal workflow buttons:

```text
Attach Service
Append IMAGE_VALID
Append BOOT_ATTEMPT
Append APP_CONFIRMED
Erase Sector Mask
Raw Command
Reset Target
RAM Run
```

Those belong in Advanced if they are exposed at all.

### 5.5 Target / Metadata Summary Card

Show read-only state, such as:

```text
Device status
Current metadata validity
Current IMAGE_VALID identity
BOOT_ATTEMPT state
APP_CONFIRMED state
Last operation result
```

This card must not implement metadata decision logic directly. It displays data returned by controller/operation results.

### 5.6 Progress / Result Summary

Required display elements:

```text
current operation name
current step
progress bar when progress data exists
result status: Success / Skipped / Cancelled / Failed
short result message
```

Cancelled must be displayed separately from Success.

---

## 6. Settings Page

The Settings page should use accordion-style sections, similar to the reference layout.

Required sections:

```text
Toolchain Settings
Connection Settings
Flash Service Settings
Temporary File Settings
Logging Settings
Advanced / Experimental
```

### 6.1 Toolchain Settings

Fields:

```text
hex2000 executable path
Browse button
validation status
```

### 6.2 Connection Settings

Fields:

```text
default baud rate
TX timeout ms
RX timeout ms
autobaud timeout ms
```

Timeouts must come from Global Settings and must not be duplicated in the Connection Ribbon.

### 6.3 Flash Service Settings

Fields:

```text
flash service image path
flash service map path
descriptor symbol
```

Do not allow descriptor address to be manually entered here. The descriptor address must be resolved from map/symbol by PC-side logic.

### 6.4 Temporary File Settings

Fields:

```text
SCI8 temporary directory
keep generated SCI8 TXT checkbox
```

### 6.5 Logging Settings

Fields:

```text
log level
save log path, optional
clear log button, optional
```

### 6.6 Advanced / Experimental

Use collapsed-by-default content. Do not put normal workflow actions here.

---

## 7. Advanced Page

Advanced Page is for engineering/debug operations. It must be visually separated from CPU1 Program.

Recommended structure:

```text
Status
Flash Operations
Metadata Operations
Execution
RAM
Raw Results
```

Use tabs or accordions. Accordions are preferred if the page would otherwise become too dense.

### 7.1 Status

Actions:

```text
Read Device Info
Read Protocol Info
Read Metadata Summary
Get Last Error
```

### 7.2 Flash Operations

Actions:

```text
Erase Image Area
Erase Sector Mask
Program Image
Verify Image
```

Show explicit note:

```text
Verify Image only verifies data. It does not write IMAGE_VALID.
```

### 7.3 Metadata Operations

Actions:

```text
Append IMAGE_VALID
Append BOOT_ATTEMPT
Append APP_CONFIRMED
```

Show required order:

```text
IMAGE_VALID -> BOOT_ATTEMPT -> APP_CONFIRMED
```

### 7.4 Execution

Actions:

```text
Run Flash App
Reset Target
```

Reset Target must be marked:

```text
Experimental / Requires DSP support
```

If unsupported, show a clear unsupported message instead of crashing.

### 7.5 RAM

Actions:

```text
Load RAM Image
Check RAM CRC
Run RAM Image
```

RAM functions are engineering features and must not appear in CPU1 Program normal workflow.

---

## 8. Visual Style Tokens

Use these as approximate style tokens. Exact values may be adjusted to match existing PySide6 styling, but spacing and hierarchy should remain consistent.

```text
font family: Segoe UI / Microsoft YaHei UI / system default sans-serif
base font size: 12-13 px
section title: 13-14 px bold
page title: 16-18 px bold
small helper text: 11-12 px
```

Colors:

```text
header background: dark navy / dark blue
section accent: teal / blue-green
main background: #F4F6F8 or similar light gray
card background: white
card border: light gray
primary action: green or blue-green
secondary action: neutral gray/blue
error: red
warning: orange/yellow
success: green
```

Do not use excessive saturated colors. Do not make the whole UI red. Keep the project header identity distinct from the reference screenshots.

Spacing:

```text
outer page margin: 12-16 px
card padding: 12-16 px
row spacing: 8-10 px
section spacing: 10-14 px
button height: 28-34 px
input height: 26-32 px
```

---

## 9. Interaction and State Rules

### 9.1 During Operations

When an operation is running:

```text
disable navigation actions that would conflict with the running operation
disable Load Image and Run appropriately
show Busy status in header or ribbon
show progress/result messages
append log lines to bottom console
```

### 9.2 Cancel

Cancel behavior is cooperative only.

```text
Cancel may stop before the next operation step.
Cancel must not force-kill a worker thread.
Run stage is not cancelable once started.
```

If Load Image is cancelled after erase/program/verify has started, show a message equivalent to:

```text
The image may be partially erased, programmed, or verified. Because IMAGE_VALID was not successfully completed, rerun Load Image before attempting to boot this image.
```

### 9.3 Error Display

Errors must be visible in three places:

```text
result summary
bottom console/log
operation detail panel, if available
```

Do not show only a modal dialog. Modal dialogs may be used for critical confirmation but must not be the only error record.

---

## 10. Architecture Rules for UI Implementation

GUI widgets must not implement upgrade logic directly.

Allowed flow:

```text
GUI widget
  -> GUI view model / controller glue
  -> ProgramController
  -> operations/*
  -> UpgradeSession.client.transact()
```

Forbidden:

```text
GUI button -> subprocess -> cpu1_upgrade CLI
GUI widget -> direct protocol command construction
GUI widget -> direct BootProtocolClient convenience calls
GUI widget -> direct serial open/read/write
GUI widget -> duplicated Flash or metadata state machine
GUI widget -> descriptor address hardcoding
```

The GUI may display metadata state, but operation-layer code owns metadata write and validation semantics.

---

## 11. Implementation Strategy for Codex

Codex must use small steps.

Preferred order:

```text
1. Add or update style constants / layout helper classes if needed.
2. Add Connection Ribbon UI skeleton.
3. Wire Connection Ribbon to existing session/controller boundary.
4. Add CPU1 Program page layout without changing operation semantics.
5. Wire Load Image / Run buttons to ProgramController.
6. Add progress/result/log display.
7. Add Advanced page after normal workflow is stable.
```

Do not rewrite the whole GUI in one task.

Do not delete existing tests unless explicitly instructed.

Do not change DSP, linker, Flash layout, protocol payloads, or operation-library semantics for UI work.

---

## 12. Acceptance Checklist

A Phase 11 GUI change is acceptable only if all relevant items pass:

```text
[ ] Top header remains persistent.
[ ] Left navigation remains persistent.
[ ] Bottom console/log drawer remains available.
[ ] Connection Ribbon has only Port, Baud, Connect/Disconnect, Status.
[ ] CPU1 Program page has exactly two main workflow buttons: Load Image and Run.
[ ] Confirm App is a checkbox option, not a standalone button.
[ ] Auto Run after Load disables Run button.
[ ] Settings page uses grouped/accordion sections.
[ ] Advanced operations are not mixed into CPU1 Program normal workflow.
[ ] GUI does not call subprocess for upgrade operations.
[ ] GUI does not directly open serial ports from widgets.
[ ] GUI does not directly construct protocol frames.
[ ] GUI does not hardcode descriptor address.
[ ] Cancel is cooperative only.
[ ] Run stage is not cancelable once started.
[ ] Existing operation-library tests still pass.
[ ] GUI import/unit tests still pass.
```

---

## 13. Non-Goals

Do not implement these as part of the visual layout work:

```text
real hardware validation
automated real serial connection tests
DSP code changes
linker cmd changes
Flash sector layout changes
protocol payload changes
CPU2 backend implementation
network transport implementation
full GUI rewrite
```

---

## 14. Suggested Repository Location

Recommended path:

```text
docs/phase11_gui_visual_layout_contract.md
```

Optional reference image storage path, if screenshots are committed later:

```text
docs/ui/reference/
```

Screenshots are reference material only. The contract above is the executable source of truth for Codex.
