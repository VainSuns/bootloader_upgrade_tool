# Windows Portable Build

The portable package contains the Python application, PySide6 runtime, GUI theme, icons, and quick-start instructions. It does not bundle `hex2000.exe`, DSP artifacts, an installer, or TI components.

## Build and run

From the repository root:

```powershell
.\tools\package_windows.ps1
```

When dependencies are already installed:

```powershell
.\tools\package_windows.ps1 -SkipInstall
```

The one-folder output is:

```text
dist\DSP28377D_Bootloader_Upgrade_Tool\
```

Launch it with:

```text
dist\DSP28377D_Bootloader_Upgrade_Tool\DSP28377D_Bootloader_Upgrade_Tool.exe
```

## External hex2000 dependency

`hex2000.exe` remains external. Startup first reads `hex2000.executable_path` from `pc/config/gui_global_settings.json`. If that setting is empty, it searches `C2000_CG_ROOT` at `<root>/bin/hex2000.exe`, then `<root>/hex2000.exe`. A non-empty invalid configured path is an error.

Global Settings > Tools can select the executable and output directory for the current run. The output directory otherwise defaults to the user cache directory.
