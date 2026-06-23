# DSP host tests

`test_boot_algorithm.c` exercises the hardware-independent C core with an
in-memory `BootIoOps` adapter. It covers CRC byte order, header resync,
DeviceInfo serialization, payload CRC errors, connection delegation, and
unsupported Phase 5 commands.

Run on Windows with a C11 GCC in `PATH`:

```powershell
powershell -ExecutionPolicy Bypass -File dsp/tests/run_host_tests.ps1
```

These tests do not replace the user-owned CCS build or real SCI DeviceInfo
integration listed in `../user_port_templates/USER_PORT_CHECKLIST.md`.

