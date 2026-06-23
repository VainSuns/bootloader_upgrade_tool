# device_info tool

`generate_device_info.py` is the narrow `.cmd MEMORY` to `device_info.json` development entry point. Parsing logic remains in the PC package for reuse and testing.

After installing the project in a Python 3.12 environment, run:

```powershell
python tools/device_info/generate_device_info.py app_cpu1.cmd device_info.json `
  --flash-region FLASHA --flash-region FLASHB
```

Repeat `--flash-region` in the exact sector-mask bit order. If omitted, regions whose names start with `FLASH` are used in linker source order.
