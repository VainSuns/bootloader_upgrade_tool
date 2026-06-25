# DSP host tests

`test_boot_algorithm.c` exercises the hardware-independent C core/service split with an
in-memory `BootIoOps` adapter. It covers CRC byte order, byte-level magic resync,
stale autobaud bytes, wrong byte phase, DeviceInfo serialization, payload CRC errors, and
service forwarding.

Run on Windows with a C11 GCC in `PATH`:

```powershell
powershell -ExecutionPolicy Bypass -File dsp/tests/run_host_tests.ps1
```

These tests do not replace the user-owned CCS build or real SCI DeviceInfo
integration listed in `../bootloader_user/templates/USER_PORT_CHECKLIST.md`.
