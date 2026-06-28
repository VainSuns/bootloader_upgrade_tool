# DSP28377D Bootloader Upgrade Tool

Source-run MVP for upgrading a TI F28377D CPU1 application from a Windows PC.

## Current MVP Scope

Implemented and hardware-validated through Phase 8:

- Windows Python 3.12 source-run GUI using PySide6.
- SCI / RS232 transport and built-in Simulator transport.
- PC-side IO Device abstraction; GUI does not talk to pySerial directly.
- `.out -> hex2000 -boot -a -sci8 -> FirmwareImage` flow.
- `C200_CG_ROOT` based `hex2000` lookup plus manual GUI path fallback.
- DeviceInfo, protocol framing, CRC, resync, and raw protocol trace logging.
- Erase, Program, Verify, DFU, and Run for CPU1 Flash app.
- Calculated-only erase sector mask from firmware address ranges.
- Reset hidden in GUI until deterministic reset policy is advertised.
- Windows one-folder portable packaging with PyInstaller.

## Quick Start

From the repository root on Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m bootloader_upgrade_tool
```

If PowerShell execution policy blocks activation, run the venv Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool
```

## Windows Portable Build

Build a one-folder portable package:

```powershell
.\tools\package_windows.ps1
```

Output:

```text
dist\DSP28377D_Bootloader_Upgrade_Tool\
```

`hex2000.exe` is not bundled; use `C200_CG_ROOT` or the manual GUI path.

## hex2000 Path Resolution

The GUI conversion path supports:

1. `C200_CG_ROOT`, for example:

   ```text
   E:\CodeComposerStudio\CCS12.7\ccs\tools\compiler\ti-cgt-c2000_22.6.1.LTS
   ```

2. Manual `hex2000.exe` path in the GUI Settings page.

The expected executable is under the compiler `bin` directory:

```text
...\bin\hex2000.exe
```

## GUI DFU + Run

1. Launch the GUI from source.
2. Select the application `.out`.
3. Confirm firmware summary and calculated sector mask. Sector A must not be included.
4. Select Serial, set the COM port and baud rate, then click Connect.
5. After autobaud, the GUI waits 100 ms and queries DeviceInfo.
6. Confirm supported features include `ERASE`, `PROGRAM`, `VERIFY`, and `RUN`.
7. Click DFU and wait for Erase + Program + Verify to finish.
8. Click Run and confirm the app starts.
9. Use Save Log if a test record is needed.

See `docs/21_gui_dfu_run_test_guide.md` for the detailed hardware checklist.

## Supported Features

- CPU1 app upgrade only.
- SCI / RS232 and Simulator.
- Flash app Erase / Program / Verify.
- GUI DFU = Erase + Program + Verify.
- Run verified CPU1 app.
- Protocol byte logging and GUI log save.
- Device, firmware, memory, and workflow status summaries.
- One-folder portable Windows build.

## Deferred Features

Not included in the source-run MVP:

- W5300 / TCP.
- CPU2 upgrade.
- App metadata, upload/readback, rollback, signing, encryption, compression.
- RAM service lib dynamic loading.
- DCSM unlock.
- Installer / MSI-style setup.
- Production reset policy exposure in GUI.

## Key Constraints

- DSP is always slave; PC GUI is always master.
- Formal protocol is a 16-bit little-endian word stream.
- SCI `'A'` autobaud is connection-layer behavior, not a protocol frame.
- No ACK/NAK word protocol.
- No DSP protocol timeout status code.
- Use Program naming, not Download.
- Flash ProgramData / VerifyData must be 8-word aligned; PC pads with `0xFFFF`.
- RamLoadData is RAM and does not use Flash alignment rules.
- Preserve Flash-resident core / RAM-resident service lib separation.

## Documentation Index

| Document | Purpose |
|---|---|
| `docs/00_project_overview.md` | Project overview |
| `docs/01_mvp_requirements.md` | MVP requirements |
| `docs/02_architecture_constraints.md` | Architecture constraints |
| `docs/03_dsp_bootloader_algorithm.md` | DSP bootloader algorithm |
| `docs/04_pc_gui_requirements.md` | PC GUI requirements |
| `docs/05_simulator_requirements.md` | Simulator requirements |
| `docs/06_device_info_tool.md` | device_info tool |
| `docs/07_user_porting_guide.md` | User porting boundary |
| `docs/08_future_features.md` | Future features |
| `docs/09_not_in_mvp.md` | Explicit non-MVP items |
| `docs/10_open_questions.md` | Open questions |
| `docs/11_codex_task_list.md` | Codex task list |
| `docs/12_mvp_acceptance_criteria.md` | MVP acceptance criteria |
| `docs/13_flash_resident_ram_lib_partition.md` | Core / service-lib split |
| `docs/14_communication_protocol.md` | Frozen protocol specification |
| `docs/15_ti_sci_flash_kernel_reference_guide.md` | TI SCI reference notes |
| `docs/16_f28377d_flash_operation_codex_guide.md` | F28377D Flash operation guide |
| `docs/19_industrial_reliability_deferred_items.md` | Deferred reliability items |
| `docs/20_phase_6_7_hardware_test_guide.md` | Phase 6/7 hardware tests |
| `docs/21_gui_dfu_run_test_guide.md` | GUI DFU + Run hardware test |
| `docs/22_mvp_acceptance_checklist.md` | Source-run MVP acceptance checklist |
| `docs/23_source_run_release_guide.md` | Source-run release guide |
| `docs/24_windows_portable_packaging_guide.md` | Windows portable packaging guide |
