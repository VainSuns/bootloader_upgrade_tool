# 22 MVP Acceptance Checklist

Use this checklist for the source-run v0.1.0 MVP.

## PC Environment

- [ ] Windows host.
- [ ] 64-bit Python 3.12.x.
- [ ] Project installed from source:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

- [ ] GUI launches:

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool
```

## Toolchain

- [ ] `hex2000.exe` resolves through `C200_CG_ROOT`, or manual GUI path is set.
- [ ] `.out` conversion creates `-boot -a -sci8` output.
- [ ] Firmware summary shows entry point, block count, total words, address ranges, calculated sector mask, and touched sectors.
- [ ] Calculated sector mask does not include Sector A.

## Transport

- [ ] Simulator connects.
- [ ] SCI / RS232 connects.
- [ ] Serial autobaud completes.
- [ ] GUI automatically queries DeviceInfo after connection.

## DeviceInfo

- [ ] Device page shows decoded `device_id`.
- [ ] Device page shows decoded `cpu_id`.
- [ ] Device page shows protocol version.
- [ ] Device page shows decoded feature flags.
- [ ] Device page shows `max_payload_words`.
- [ ] Device page shows `max_data_words`.
- [ ] Device page shows `boot_mode`.
- [ ] Device page shows `kernel_layout`.
- [ ] Device page shows `revision_id`.
- [ ] Device page shows `uid_unique`.

## GUI Operations

- [ ] Reset is hidden.
- [ ] Sector mask is calculated-only.
- [ ] Operation buttons follow advertised feature flags.
- [ ] Long operations do not freeze the UI.
- [ ] Save Log writes the console log to a file.

## Hardware Acceptance

- [ ] Phase 6.3 `.out -> hex2000 -> Program -> Verify` passes.
- [ ] Phase 7.1 Run passes.
- [ ] GUI DFU + Run passes.
- [ ] App starts after Run, for example LED blinks.

## Deferred

These are not required for v0.1.0:

- [ ] Installer / PyInstaller.
- [ ] W5300 / TCP.
- [ ] CPU2 upgrade.
- [ ] Metadata, upload/readback, rollback, signing, encryption, compression.
- [ ] RAM service lib dynamic loading.
- [ ] DCSM unlock.
