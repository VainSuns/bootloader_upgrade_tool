# GUI Style Specification

## Visual Direction

Use the approved **Control Room Blue** style. The UI should feel like a quiet
desktop engineering control tool: light, dense, readable, and stable. It may
borrow UniFlash-like information architecture patterns, but must not copy TI
branding, logos, icons, screenshots, or proprietary layout details.

The style source is UI UX Pro Max's professional minimal / Swiss-style guidance:
semantic color tokens, clear hierarchy, visible focus states, restrained
effects, and no decorative visuals that do not help programming, verification,
or fault diagnosis.

## Colors

| Token | Value | Use |
|---|---|---|
| `app.background` | `#F6F8FB` | main work area |
| `surface` | `#FFFFFF` | cards, forms, menus, dialogs |
| `surface.subtle` | `#F8FAFC` | read-only fields, console header |
| `surface.hover` | `#EEF4FB` | hover state |
| `border` | `#D7DEE8` | default separator |
| `border.strong` | `#AEBBCD` | input and splitter emphasis |
| `text.primary` | `#0F172A` | main text |
| `text.secondary` | `#334155` | labels and secondary text |
| `text.muted` | `#64748B` | hints and disabled-adjacent text |
| `text.disabled` | `#94A3B8` | disabled controls |
| `topbar.background` | `#17324D` | top application bar |
| `sidebar.background` | `#FFFFFF` | left navigation |
| `sidebar.active.background` | `#EAF3FF` | selected navigation item |
| `primary` | `#2563EB` | Program / DFU / primary action |
| `primary.hover` | `#1D4ED8` | primary hover |
| `primary.pressed` | `#1E40AF` | primary pressed |
| `info` | `#0E7490` | information and protocol accents |
| `success` | `#16803C` | connected, complete, success |
| `warning` | `#B7791F` | busy, warning, attention |
| `error` | `#C62828` | error and dangerous actions |
| `console.background` | `#FFFFFF` | log console body |
| `console.panel` | `#EEF2F6` | console frame and collapsed bar |
| `console.text` | `#0F172A` | console text |

Do not turn the GUI into a one-color blue theme. Blue is for structure and
primary actions; green, amber, red, neutral surfaces, and the light console
panel must keep their semantic roles.

## Typography

- Use Windows platform UI fonts: `Segoe UI` for UI text and `Consolas` /
  `Cascadia Mono` for logs, addresses, words, protocol bytes, and file paths.
- Use normal letter spacing.
- Use compact, clear type sizes: 13 px body, 12 px helper/section labels, 14 px
  card and expander titles, 17 px application title.
- Use weight instead of color alone for hierarchy: 600 for card titles,
  selected navigation, primary buttons, and important status text.

## Spacing

- Main window page margin: 16 px.
- Card padding: 16 px.
- Card spacing: 12 px.
- Form row spacing: 8-10 px.
- Button and input height: 32 px for main controls, 28 px for tool buttons.
- Navigation row height: 40 px.
- Avoid nested cards; use separators or expanders inside a card.

## Shape And Elevation

- Radius stays small: cards 6 px, inputs/buttons 4 px, badges 10 px or less.
- Use 1 px borders for most surfaces.
- Use only subtle shadows on menus, popups, and dialogs. Do not use large
  floating-card shadows in normal page layout.

## Interaction States

Every common control must define:

- default;
- hover;
- pressed where applicable;
- focus;
- disabled;
- read-only when applicable;
- selected/checked when applicable.

Focus must remain visible for keyboard use. Disabled controls must look
non-interactive but still readable enough to explain state.

## Console

The console remains a utility surface, but it should stay in the same light
theme family as the rest of the main window:

- white or subtle-gray background;
- clear 1 px border from the work area;
- monospaced text;
- compact tool buttons;
- level labels: `INFO`, `WARN`, `ERROR`, `SUCCESS`, `PROTO`;
- raw protocol trace disabled by default and controlled by Settings.
