# PC Source

`src/bootloader_upgrade_tool` contains PC-side parsing, protocol, IO Device,
Simulator, workflow, and PySide6 GUI packages.

After installing the project in a Python 3.12 environment, run the GUI from
source:

```powershell
python -m bootloader_upgrade_tool
```

The GUI flow depends only on `PcIoDevice`. pySerial usage is isolated inside
`SerialIoDevice`; Simulator mode does not require serial hardware.
