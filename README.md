# DSP28377D Bootloader Upgrade Tool

Windows/PySide6 upgrade tool for TI TMS320F28377D targets. It combines a Flash-resident DSP bootloader, a downloaded Flash Service, and shared PC CLI/GUI operations.

The CPU1 SCI-A/RS232 product path is implemented. CPU2 support and the optional W5300/TCP transport are deferred.

## Run from source

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m bootloader_upgrade_tool
```

If activation is blocked, invoke `.\.venv\Scripts\python.exe` directly.

## hex2000

Image conversion resolves `hex2000.exe` from `pc/config/gui_global_settings.json`, then from `C2000_CG_ROOT`. Global Settings can override the executable and output paths for the current run. TI's tool is an external dependency and is not bundled.

## Documentation

Start with the short [documentation index](docs/README.md). It links the product scope, domain contracts, porting/build guides, and release notes.
