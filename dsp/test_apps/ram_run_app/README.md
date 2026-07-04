# RAM_RUN test app template

This is a minimal source template for Phase 10.3 hardware validation.

Build it as a RAM-linked CPU1 app with:

- entry point inside a confirmed allowed RAM write region;
- `RAM_RUN_MARKER_ADDR` defined by the user build;
- marker address outside bootloader-owned RAM;
- marker address not equal to `0x0000`;
- no Flash API dependency.

Pick the marker address from a confirmed safe RAM region in the user's linker
map. This template intentionally does not provide a universal default marker
address.

Then run:

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool.tools.ram_run --transport serial --port COM10 --baud 9600 --image path\to\ram_run_app.out
```

The app writes `0xA55A` to `RAM_RUN_MARKER_ADDR` and loops.
