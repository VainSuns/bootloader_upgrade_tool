# GUI Style Specification

## Visual Direction

The UI should feel like a quiet engineering tool: dense, readable, and stable.
Avoid decorative visuals that do not help programming, verification, or fault
diagnosis.

## Colors

| Token | Value | Use |
|---|---|---|
| `app.background` | `#F5F7FA` | main background |
| `card.background` | `#FFFFFF` | cards and panels |
| `card.border` | `#D9DEE7` | card border |
| `topbar.background` | `#17324D` | top application bar |
| `sidebar.background` | `#263238` | navigation sidebar |
| `primary` | `#1976D2` | primary action |
| `secondary` | `#607D8B` | secondary action |
| `success` | `#2E7D32` | success badge/log |
| `warning` | `#F9A825` | warning badge/log |
| `error` | `#C62828` | error badge/log |
| `console.background` | `#111827` | console background |
| `console.text` | `#D1D5DB` | console text |

Do not let the application become a one-color theme. Use restrained contrast
between shell, cards, actions, and console.

## Typography

- Use the platform default UI font unless there is a clear reason to override.
- Use normal letter spacing.
- Use compact headings inside cards.
- Use monospaced text only for addresses, words, protocol bytes, logs, and file
  paths.

## Spacing

- Main window content margin: 12-16 px.
- Card padding: 12 px.
- Card spacing: 12 px.
- Button height: stable and consistent.
- Avoid nested cards.

## Components

Cards should have:

- white background;
- 1 px border;
- radius no larger than 8 px;
- clear title;
- compact content.

Buttons:

- primary: Program / DFU style actions;
- secondary: Browse / Get Device Info / Clear;
- danger: destructive or policy-gated actions only;
- disabled states must be visually clear.

Status badges:

- Disconnected;
- Connected;
- Busy;
- Complete;
- Warning;
- Error.

Progress:

- visible for Erase / Program / Verify / DFU / Run;
- no layout shift when progress updates.

Console:

- dark background;
- timestamped lines;
- level labels: `INFO`, `WARN`, `ERROR`, `SUCCESS`, `PROTO`;
- save buttons for `.log` and `.jsonl`.
