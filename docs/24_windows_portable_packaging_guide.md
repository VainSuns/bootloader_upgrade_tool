# 24 Windows Portable Packaging Guide

This guide creates the v0.1.0 Windows one-folder portable build.

## Scope

The package includes the Python app, PySide6 runtime, GUI theme, and GUI images.

The package does not include:

- `hex2000.exe`;
- DSP code;
- protocol changes;
- Flash service changes;
- installer logic.

## Build

From the repository root:

```powershell
.\tools\package_windows.ps1
```

If dependencies are already installed:

```powershell
.\tools\package_windows.ps1 -SkipInstall
```

Output:

```text
dist\DSP28377D_Bootloader_Upgrade_Tool\
```

Run:

```text
dist\DSP28377D_Bootloader_Upgrade_Tool\DSP28377D_Bootloader_Upgrade_Tool.exe
```

The script copies `README_quick_start.md` into the output folder.

## hex2000

`hex2000.exe` remains external. Configure it with one of:

- `C200_CG_ROOT`;
- GUI Settings manual `hex2000.exe` path.

Example:

```text
E:\CodeComposerStudio\CCS12.7\ccs\tools\compiler\ti-cgt-c2000_22.6.1.LTS\bin\hex2000.exe
```

## Acceptance

- [ ] Packaged exe launches.
- [ ] Theme and icon load.
- [ ] Simulator mode connects.
- [ ] Serial COM port opens.
- [ ] Selecting `.out` works.
- [ ] Manual `hex2000.exe` path works.
- [ ] GUI DFU + Run passes.
- [ ] Save Log writes a file.
