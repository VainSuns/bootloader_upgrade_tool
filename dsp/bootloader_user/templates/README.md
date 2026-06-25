# DSP user port templates

These files define the hardware-dependent work that must be completed by the
product integrator. They are deliberately excluded from the host test build and
contain compile-time guards so a stub cannot be shipped accidentally.

Copy the templates into the user's CCS project, remove each `#error` only after
the corresponding implementation is complete, and keep hardware code outside
`bootloader_core/` and `flash_service_lib/`.

DSP-facing functions return at most 32 bits. Use output pointers for
`BootIoOps`, `BootDeviceInfo`, error structures, and other larger results.

- `boot_user_io_template.c`: SCI autobaud, blocking receive-byte IO, and word IO.
  `get_byte` has no timeout parameter; connection timeout remains higher-level policy.
- `boot_user_flash_template.c`: address policy and the user-owned F021 wrapper boundary.
- `boot_user_ram_template.c`: Future RAM region policy and word writes.
- `boot_user_device_info_template.c`: product/device capabilities reported to the PC.
- `boot_user_integration_template.c`: outer-loop wiring after product initialization.
- `USER_PORT_CHECKLIST.md`: integration and target-validation gates.

Codex must not fill in PLL, Flash wait-state, DCSM, pump semaphore, raw F021,
interrupt/vector, watchdog, or linker placement details.
