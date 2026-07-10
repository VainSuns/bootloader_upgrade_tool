# Flash-sector selector contract

The Advanced / Flash custom erase selector edits a local selection only.

- Sector options are supplied as a sequence of `FlashSectorOption` values.
- The widget does not assume a fixed number of sectors.
- Protected sectors are visible but disabled.
- The selected mask is derived from each option's explicit `bit_index`.
- No erase operation, service attach, transport call, or target access occurs.
- Sector A is protected in the default TMS320F28377D CPU1 option list.
