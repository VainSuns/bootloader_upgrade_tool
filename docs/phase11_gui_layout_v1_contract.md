# Phase 11 GUI Layout V1.0 Contract

## 1. Contract Status

This document is the long-term visual and structural authority for the GUI. It
defines window, page, and Widget structure; `objectName`; static visual states;
layout dimensions; theme, icon, and presentation rules.

Runtime state ownership, operation admission, resource lifecycle, Evidence,
MetadataSnapshot, task execution, and operation sequencing are defined by
RAC-V2 and the PC operation-library contract. This document is not an
implementation plan and does not redefine those runtime contracts.

The V1.0 design is frozen. Redesign beyond this document requires explicit user
approval.

## 2. Scope and Hardware Boundary

This contract covers PySide6 layout, visual styling, icons, preview data, and
GUI-only interactions such as navigation and Console collapse/expand.

Layout and preview work must not:

- open a real COM port;
- perform SCI autobaud;
- call the legacy CLI through subprocess;
- erase, program, or verify real Flash;
- write real metadata;
- send real RUN or reset commands;
- perform W5300/TCP communication;
- perform CPU2 bring-up;
- change DSP initialization, linker configuration, Flash layout, or metadata contracts.

DSP-touching GUI actions follow:

```text
GUI widgets
  -> GUI controller / view-model glue
  -> images/* for PC-side file preparation only
  -> operations/* public APIs
  -> OperationContext / FlashOperationContext
  -> active TargetProfile / CommandSet
  -> UpgradeSession.client.transact()
  -> BootProtocolClient / FrameReader
  -> ByteTransport
```

Widgets never select command IDs, construct protocol frames, call pySerial or sockets, or duplicate image/Flash/metadata/RUN sequencing.

## 3. Application and Window Baseline

- GUI toolkit: PySide6.
- Application style: Fusion.
- Default font: Segoe UI, 9 pt.
- Default window: 1440 x 900 logical pixels.
- Hard minimum window: 1180 x 680 logical pixels.
- Validation sizes: 1280 x 760, 1440 x 900, and 1920 x 1080.
- Validation DPI: 100%, 125%, and 150%.
- Use Qt logical pixels; do not multiply dimensions by device-pixel ratio.
- Use the native Windows title bar.
- First launch centers a 1440 x 900 window and clamps it to the available screen.
- At heights below 760 px, Console starts collapsed.
- This contract defines default geometry and splitter metrics; persistence
  ownership and lifecycle follow RAC-V2 and the applicable settings contract.

## 4. Main Window Shell

Frozen hierarchy:

```text
BootloaderMainWindow
└─ mainRoot
   ├─ topRibbonShell
   │  ├─ titleTabRow
   │  │  └─ ribbonTabBar
   │  └─ ribbonContentRow
   │     └─ ribbonPageStack
   └─ workspaceVerticalSplitter
      ├─ mainAreaSplitter
      │  ├─ navigationPanel
      │  │  └─ navigationTree
      │  └─ pageContentHost
      │     └─ pageContentStack
      └─ bottomDock
         ├─ bottomDockHeader
         └─ bottomConsoleBody
            └─ consoleOutput
```

Core object names:

```text
bootloaderMainWindow
mainRoot
topRibbonShell
titleTabRow
ribbonTabBar
ribbonContentRow
ribbonPageStack
workspaceVerticalSplitter
mainAreaSplitter
navigationPanel
navigationTree
pageContentHost
pageContentStack
bottomDock
bottomDockHeader
consoleTitle
consoleAutoScrollButton
consoleClearButton
consoleExpandButton
bottomConsoleBody
consoleOutput
```

Decorative frames and layouts do not require object names.

### 4.1 Shell Metrics

- `mainRoot` contents margins: 0.
- `mainRoot` spacing: 0.
- Ribbon total height: 120 px.
- Ribbon tab row: 34 px.
- Ribbon content row: 86 px.
- Navigation default width: 224 px.
- Navigation minimum width: 208 px.
- Navigation maximum width: 260 px.
- Main horizontal splitter handle: 4 px.
- Workspace vertical splitter handle: 5 px.
- Page content minimum width: 720 px.
- Main area minimum height: 360 px.
- Navigation and page content are non-collapsible.

## 5. Ribbon

Ribbon tabs remain exactly:

```text
Session
Operate
View
Settings
```

Default selected tab: `Operate`.

Tab metrics:

- height: 34 px;
- minimum width: 76 px;
- horizontal padding: 16 px;
- gap: 2 px;
- row side margins: 10 px.

Ribbon content metrics:

- horizontal margins: 8 px;
- top margin: 4 px;
- bottom margin: 2 px;
- group gap: 4 px;
- group internal horizontal padding: 8 px;
- caption height: 18 px;
- separator: 1 px.

Large Ribbon buttons:

- icon: 24 px;
- height: 58 px;
- preferred width: 70 px;
- minimum width: 64 px;
- maximum width: 88 px.

### 5.1 Session Ribbon

The Session Ribbon preserves the current functional content:

```text
File: New, Open, Save, Save As
Recent
Session State: Current, Modified, Path
```

Spacing, icons, object names, and visual roles are frozen here. Runtime enabled
state and command semantics follow RAC-V2 and controller/runtime contracts.

### 5.2 Operate Ribbon

Groups:

```text
Transport
Operate
Status
```

- Transport minimum width: 300 px.
- Operations minimum width: 230 px.
- Status minimum width: 170 px.
- Remaining space is stretch.
- SCI fields: Port and Baud.
- TCP tab remains visible.
- Its enabled state follows the active transport capability.
- It shows unavailable/disabled while TCP capability is absent.
- Normal operation buttons remain Connect/Disconnect, Load Image, and Run.
- The normal GUI does not add or restore a DFU button.
- CPU1 and CPU2 status rows remain visible with colored status dots and text.
- Status-row height: 24 px; row gap: 4 px.

### 5.3 View Ribbon

Contains Console and Logs controls. View Ribbon object names use a `view` prefix to avoid collisions with the global Console header, for example:

```text
viewConsoleToggleButton
viewConsoleClearButton
viewConsoleAutoScrollButton
viewOpenLogsButton
viewExportLogsButton
viewOpenLogFolderButton
```

### 5.4 Settings Ribbon

Contains:

```text
Open Settings
Save Global
Reload Global
```

Open Settings performs GUI navigation. Save/Reload availability and persistence
semantics follow the settings and Runtime contracts.

## 6. Navigation

Navigation hierarchy remains exactly:

```text
Program
  CPU1
  CPU2
Settings
Memory
  CPU1
  CPU2
Advanced
Logs
```

Navigation metrics:

- panel padding: 8 px;
- parent item height: 34 px;
- child item height: 32 px;
- icon: 16 px;
- icon/text gap: 8 px;
- indentation: 18 px;
- border: 1 px.

Internal navigation uses a stable `PageId` enum, not display strings or naked stack indexes:

```text
program.cpu1
program.cpu2
settings
memory.cpu1
memory.cpu2
advanced
logs
```

Every navigation entry point calls one `navigate_to(page_id)` method so the page stack, navigation selection, and Ribbon navigation state stay synchronized.

## 7. Page Shell Rules

Common page metrics:

- left/right margins: 16 px;
- top/bottom margins: 14 px;
- block spacing: 12 px;
- page-title row: 36 px;
- no breadcrumb;
- outer shell never scrolls.

Pages use internal scroll areas only where specified. Nested scroll areas are not allowed. Horizontal page scrolling is not allowed.

## 8. Program Pages

CPU1 and CPU2 use one shared component:

```text
ProgramTargetPage(target="cpu1" | "cpu2")
```

Hierarchy:

```text
ProgramTargetPage
├─ pageTitleRow
└─ programBodyScrollArea
   └─ programContentContainer
      └─ programHorizontalSplitter
         ├─ workflowPane
         │  ├─ appImageCard
         │  ├─ programOptionsCard
         │  └─ operationProgressCard
         └─ statePane
            ├─ statusSummaryCard
            └─ detailsResultCard
```

Metrics:

- maximum content width: 1480 px, centered;
- splitter handle: 6 px;
- splitter children are non-collapsible;
- default ratio: 58:42;
- workflow minimum width: 520 px;
- workflow preferred width: 640-720 px;
- workflow maximum width: 880 px;
- state minimum width: 360 px;
- state preferred width: 440-560 px;
- state maximum width: 640 px.

Cards:

- App Image minimum height: 150 px;
- Options minimum height: 82 px;
- Progress minimum height: 124 px and vertical stretch 1;
- Status Summary minimum height: 218 px;
- Details/Result minimum height: 150 px and vertical stretch 1.

App Image fields:

```text
App path
File name
Entry point
Image size
CRC32
Parse status
Target
```

Options:

```text
Force Load
Auto Run after Load
Confirm App
```

Progress:

```text
Current operation
Stage
Progress
Processed/total statistics
Message
Cancel
```

Status Summary:

```text
Metadata Valid
Entry Point Valid
IMAGE_VALID
Flash App CRC32
BOOT_ATTEMPT
Loaded Image Matches
APP_CONFIRMED
Confirmed Bootable
```

Details/Result uses a read-only `QPlainTextEdit` with Copy and Clear controls. Normal workflow buttons remain in the Operate Ribbon; the Program page does not add Erase/Program/Verify/SERVICE_ATTACH buttons.

## 9. Settings Page

There is one top-level Settings page:

```text
settingsPage
├─ pageTitleRow
├─ settingsScopeTabs
└─ settingsContentStack
   ├─ currentSettingsPage
   └─ globalSettingsPage
```

- content maximum width: 1360 px, centered;
- scope tabs: Current Configuration and Global Configuration;
- scope-tab height: 38 px;
- scope-tab minimum width: 170 px.

Each scope uses:

```text
scopePage
├─ horizontal splitter
│  ├─ category panel/list
│  └─ category content stack
└─ fixed action bar
```

Metrics:

- splitter handle: 5 px;
- category default width: 208 px;
- category minimum width: 184 px;
- category maximum width: 232 px;
- category row height: 36 px;
- content minimum width: 620 px;
- action-bar height: 52 px;
- buttons minimum size: 96 x 32 px;
- form row minimum height: 38 px;
- label width: 180 px;
- input minimum height: 32 px;
- Browse button: 38 x 32 px.

Current categories:

```text
Connection
Target
Program Options
```

Current actions:

```text
Reset Current
Apply Current
```

Global categories:

```text
Tools
Flash Service
Transport
Logging
GUI Behavior
```

Global actions:

```text
Reload Global
Save Global
```

The Flash Service view displays one shared `AppResourceProvider` resource:

```text
Provider
Service image
Service map
Descriptor symbol
Descriptor address
Preparation status
```

These fields are read-only resource state. Service paths do not belong to
Global Settings or Session persistence, are not end-user editable, and are not
stored as independent CPU1/CPU2 paths. `AppResourceProvider` supplies the source
artifact. Each operation materializes it against the active `TargetProfile` and
validates RAM ranges, descriptor, CRC, ABI, and capabilities. Hosting this
read-only view under Settings does not make the resource a Global Setting.

Erase Settings do not belong in Settings; they are located in Advanced/Flash.

## 10. Advanced Page

Frozen top-level structure:

```text
advancedPage
├─ pageTitleRow
└─ advancedVerticalSplitter
   ├─ advancedTabs
   │  ├─ Diagnostics
   │  ├─ Flash
   │  ├─ Metadata
   │  ├─ Execution
   │  └─ RAM Image
   └─ advancedResultDetailsCard
```

Metrics:

- maximum content width: 1480 px;
- splitter handle: 6 px;
- top/result default ratio: 68:32;
- tabs minimum height: 260 px;
- result minimum height: 130 px;
- tab-bar height: 38 px;
- tab minimum width: 118 px;
- tab icon: 16 px.

Each tab has one internal vertical scroll area. The shared result panel remains outside the tabs.

### 10.1 Diagnostics

Contains read-only diagnostic actions and summaries:

```text
Refresh Status
Read Device Info
Read Protocol Info
Read Metadata Summary
Get Last Error
```

SERVICE_ATTACH is not exposed as a public action.

### 10.2 Flash

Contains advanced-only low-level actions:

```text
Erase
Program Only
Verify Only
```

Verify Only does not write IMAGE_VALID.

Erase scope:

```text
Required App Sectors
Entire Application Region
Custom Sector Mask
```

Default scope: Required App Sectors.

The reusable Flash-sector selector follows this widget contract:

- selection is local UI state until an operation request is created;
- sector options are injected by the active `TargetProfile` / `FlashLayout`;
- the number of sectors is not fixed;
- sector names are supplied by option data, not generated or assumed by the Widget;
- protected options remain visible but disabled;
- the protected label is supplied by option data;
- mask construction uses each option's explicit `bit_index`;
- the widget does not access Flash operations, services, transport, protocol,
  target discovery, or fixed CPU/sector tables;
- the Widget does not know Sector A, CPU1, or the F28377D sector table.

The concrete protected sector is `TargetProfile` / `FlashLayout` business data.
A CPU1 page may display Sector A only when CPU1 profile data supplies it.

The wording `Entire Flash` is prohibited. Custom-mask controls may remain
visible, but unsupported choices show unavailable/disabled according to Runtime
capability and safety validation.

### 10.3 Metadata

Metadata actions remain separate and ordered:

```text
Write IMAGE_VALID
Write BOOT_ATTEMPT
Write APP_CONFIRMED
```

The UI must explain:

```text
IMAGE_VALID
  -> BOOT_ATTEMPT
  -> APP_CONFIRMED
```

BOOT_ATTEMPT and APP_CONFIRMED bind to the current IMAGE_VALID. Records from an older image cannot be reused.

### 10.4 Execution

Contains:

```text
Run Flash App
Reset Target
```

No Stop/Abort/Cancel control is shown after Run or Reset control transfer. RUN
semantics and admission are defined by RAC-V2 and the operation-library
contract.

Reset Target shows unavailable/disabled when deterministic Reset capability is
not advertised. This visual state does not claim production Reset support.

### 10.5 RAM Image

CPU1 and CPU2 cards remain side by side. Each contains:

```text
RAM image path
File name
Entry point
Image size
CRC32
Prepared state
Load RAM Image
Check RAM CRC
Run RAM Image
```

Load RAM Image, Check RAM CRC, and Run RAM Image remain separate visible
controls. Their operation semantics and gates are defined outside this layout
contract.

### 10.6 Shared Advanced Result

Contains:

```text
Result header
State badge
Copy
Export
Clear
Operation
Stage
Progress bar
Processed/total
Cancel
Read-only result text
```

Cancel appears only when the active operation reports a safe cancellable stage. It is not shown for RUN or Reset.

## 11. Memory Pages

CPU1 and CPU2 use one shared component:

```text
MemoryTargetPage(target="cpu1" | "cpu2")
```

Structure:

```text
MemoryTargetPage
├─ pageTitleRow
├─ memoryControlCard
└─ memoryHorizontalSplitter
   ├─ memoryTableCard
   └─ memoryDetailsCard
```

Controls:

```text
Start Address
Word Count
Display Format
Search
Refresh
Export
```

- default Word Count: 256;
- UI range: 1-4096, not a protocol promise;
- formats: Hex16, Unsigned, Signed, ASCII;
- Search operates on currently loaded local table data.

Table columns:

```text
Address
+0 +1 +2 +3 +4 +5 +6 +7
```

- eight 16-bit words per row;
- header height: 32 px;
- row height: 26 px;
- Address column: 104 px;
- word column minimum: 58 px;
- table is read-only;
- no Write/Modify/Commit/Patch/Fill controls.

Details fields:

```text
Address
Offset
Hex16
Unsigned
Signed
ASCII
Copy
```

Splitter metrics:

- handle: 6 px;
- table/details ratio: 74:26;
- table minimum width: 600 px;
- details minimum width: 260 px.

Real memory reading and writing are deferred until an explicit operation API is approved. Preview data must be clearly labelled as layout preview data.

## 12. Logs Page

Structure:

```text
logsPage
├─ pageTitleRow
├─ logsFilterBar
└─ logsHorizontalSplitter
   ├─ logsTableCard
   └─ logDetailsCard
```

The Logs page is structured history; it is not the global real-time Console and must not share the same widget instance.

Filters:

```text
Level
Source
Search
Reset Filter
Export
Open Folder
Clear Logs
```

Level choices:

```text
All
Debug
Info
Warning
Error
Success
Protocol
```

Table columns:

```text
Time
Level
Source
Operation
Message
```

`Stage` belongs in the details pane.

Metrics:

- maximum content width: 1600 px;
- filter bar: 48 px;
- splitter handle: 6 px;
- table/details ratio: 70:30;
- table minimum width: 620 px;
- details minimum width: 300 px;
- table header: 32 px;
- row height: 28 px.

Clear Logs does not clear Console. Clear Console does not clear Logs.

## 13. Global Console

Console is one global bottom panel and is not recreated during page navigation.

Structure:

```text
bottomDock
├─ bottomDockHeader
│  ├─ consoleIcon
│  ├─ consoleTitle
│  ├─ consoleStateBadge
│  ├─ consoleCopyButton
│  ├─ consoleAutoScrollButton
│  ├─ consoleClearButton
│  └─ consoleExpandButton
└─ bottomConsoleBody
   └─ consoleOutput
```

Metrics:

- default expanded height: 160 px;
- minimum expanded height: 120 px;
- collapsed height: 34 px;
- header height: 34 px;
- tool button: 26 x 26 px;
- tool icon: 16 px.

Collapse behavior:

1. save the current valid expanded height;
2. hide Console body;
3. reduce the bottom pane to 34 px;
4. restore the previous height when expanded;
5. clamp restored height to preserve a 360 px minimum main area.

Console uses `QPlainTextEdit`, not `QTextEdit` or HTML. It uses no line wrap and later limits block count through configuration.

Frozen text format:

```text
[HH:MM:SS.mmm] [LEVEL] Source: Message
```

Levels:

```text
DEBUG
INFO
WARNING
ERROR
SUCCESS
PROTOCOL
```

Console header is light; Console body is dark. A `QSyntaxHighlighter` colors the timestamp, level, source, and weak Warning/Error row backgrounds. Copy and export always produce plain text.

Console colors:

```text
background        #171B22
default text      #D6DAE1
timestamp         #778192
source            #AEB7C6
DEBUG             #8B95A5
INFO              #69A7F8
WARNING           #F2B84B
ERROR             #FF6B6B
SUCCESS           #67C587
PROTOCOL          #B79AF4
warning row bg    #2B261B
error row bg      #302025
```

## 14. Theme and QSS Contract

Runtime loading path:

```text
app.py
  -> QApplication + Fusion + application font
  -> theme.load_theme(app)
  -> resources/styles/theme.qss
```

`styles.py::APP_QSS` is retired. `styles.py` may temporarily provide compatibility imports from `layout_metrics.py`, but it must not remain a theme source.

Qt QSS has no standard CSS variables, so the project uses:

```text
theme_tokens.py      token values
theme.qss            @TOKEN@ placeholders
theme.py              load, replace, validate, apply
```

Theme loading fails on missing files, unknown tokens, or unresolved placeholders.

Python owns:

```text
layout
margins and spacing
sizes and size policies
splitter ratios
visibility and enabled state
objectName
icon size
dynamic properties
```

QSS owns:

```text
colors
typography
borders and radii
hover, pressed, focus, disabled, checked states
semantic state presentation
scrollbars
```

Large inline `setStyleSheet()` blocks and status-dot inline styling are prohibited.

Dynamic properties are limited to:

```text
uiRole
variant
state
level
scope
```

Common values:

```text
uiRole: pageTitle, card, cardHeader, cardTitle, fieldLabel, valueLabel,
        helperText, statusDot, statusBadge, banner, consolePanel
variant: primary, secondary, ghost, ribbon, toolbar, consoleTool,
         danger, dangerGhost, link
state: neutral, idle, unknown, disconnected, connecting, connected,
       busy, success, warning, error, dirty, clean, protected, unavailable
level: debug, info, warning, error, success, protocol
scope: current, global
```

Property changes use one helper that sets properties and repolishes the widget.

## 15. Visual Tokens

Primary light-theme tokens:

```text
WINDOW_BG          #F3F5F7
SURFACE            #FFFFFF
SURFACE_SUBTLE     #F7F9FB
SURFACE_SUNKEN     #EEF1F4
BORDER             #D6DCE4
BORDER_STRONG      #B8C2CF
TEXT_PRIMARY       #1F2937
TEXT_SECONDARY     #526173
TEXT_MUTED         #7B8794
TEXT_DISABLED      #A6AFBA
PRIMARY            #1677FF
SUCCESS            #2E7D32
WARNING            #ED6C02
ERROR              #D32F2F
```

- Card border: 1 px.
- Card radius: 6 px.
- Input/button radius: 4 px.
- Badge radius: 10 px.
- No card shadows or `QGraphicsDropShadowEffect`.
- Status badges always include text; status dots are auxiliary only.
- Checkbox and radio indicators use Fusion/native behavior; do not replace them with SVGs in V1.0.

## 16. Tabler Icon Contract

Pinned source:

```text
@tabler/icons 3.44.0
Outline
24 x 24
stroke width 2
MIT
```

Project resources contain only the selected subset and license:

```text
resources/icons/icon_manifest.json
resources/icons/resolved_manifest.json
resources/icons/tabler/outline/*.svg
resources/licenses/TABLER_ICONS_LICENSE.txt
```

Page code uses semantic manifest keys through `IconManager`; it never opens a raw SVG path directly.

`IconManager` validates semantic keys, resolves project resources, creates icon modes, handles tones, and caches by semantic key, tone, size, DPR, and theme ID. Status dots remain QSS circles.

## 17. Module Boundary

Approved target structure:

```text
gui/
├─ app.py
├─ main_window.py
├─ navigation.py
├─ layout_metrics.py
├─ theme_tokens.py
├─ theme.py
├─ ui_state.py
├─ icon_manager.py
├─ layout_preview.py
├─ widgets/
│  ├─ card.py
│  ├─ page_header.py
│  ├─ status_widgets.py
│  ├─ form_rows.py
│  ├─ navigation_panel.py
│  ├─ console_widget.py
│  └─ ribbon/
├─ pages/
│  ├─ program_page.py
│  ├─ memory_page.py
│  ├─ logs_page.py
│  ├─ settings/
│  └─ advanced/
├─ syntax/
│  └─ console_highlighter.py
└─ resources/
```

`main_window.py` is an assembly and navigation layer. It does not contain page form details, QSS strings, raw SVG paths, or operation calls.

View modules do not own Runtime business truth and do not bypass
`RuntimeBackend`, controller/runtime glue, or the operation library. Concrete
Runtime architecture and import direction are defined by RAC-V2.

## 18. Preview Policy

Static preview mode may:

- navigate all pages;
- show CPU2 pages;
- show TCP disabled;
- show sample status states;
- show clearly labelled Memory, Logs, and Console preview data;
- exercise local navigation, tabs, filtering, selection, and Console collapse.

Preview mode must not create a fake UpgradeSession, open serial ports, call operations, or claim real hardware success. Every sample must include wording such as `Layout Preview`, `Preview Data`, or `Static Example`.

## 19. CPU2 and TCP Presentation Policy

- CPU2 pages and object structure may remain present;
- when CPU2 capability is unavailable, CPU2 actions show unavailable/disabled;
- CPU1 defaults must not simulate CPU2 state or behavior;
- when TCP capability is unavailable, TCP shows unavailable/disabled;
- visible placeholders do not claim implemented capability;
- this layout contract does not authorize a CPU2 or TCP backend.

## 20. Responsive Acceptance

### 1280 x 760

- no main-window horizontal scrollbar;
- Ribbon does not horizontally scroll;
- Program remains two-column;
- Settings action bar remains visible;
- Advanced result pane remains at least 130 px;
- Memory and Logs remain split views;
- Console may remain expanded at 160 px.

### 1440 x 900

Primary screenshot-review size. All layouts show their preferred proportions.

### 1920 x 1080

Content uses the documented maximum widths and stays centered rather than stretching forms indefinitely.

### 1180 x 680

- Console starts collapsed at 34 px;
- no mobile or single-column redesign;
- page-specific vertical scrolling is allowed;
- core controls remain visible;
- no main-window horizontal scrolling.

## 21. Verification

Applicable static checks:

```text
Python compile
QT_QPA_PLATFORM=offscreen GUI smoke tests
layout object-name tests
theme token validation
icon manifest and file validation
navigation synchronization tests
Console highlighter tests
preview-mode hardware-import checks
git diff --check
```

No verification command may connect to real hardware.

Screenshot matrix:

```text
1280 x 760
1440 x 900
1920 x 1080
100%, 125%, 150% DPI
```

Review pages/states include Program Idle/Busy/Success/Error, Settings Current and Global, all Advanced tabs, Memory, Logs, and Console expanded/collapsed.

## 22. Authority Boundary

GUI Layout V1 does not authorize changes to Runtime, operations, protocol, DSP,
or Target contracts. The current user task and higher-level authorities define
which files may change.

Runtime changes must not independently alter the frozen page structure, Widget
visual contract, `objectName`, navigation hierarchy, Ribbon order, or TaskDialog
visual structure defined here.
