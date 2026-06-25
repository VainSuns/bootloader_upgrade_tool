# Public DSP headers

Shared Phase 4/5 upper-layer declarations. `boot_flash_port.h` and
`boot_ram_port.h` declare user-owned boundaries only; they contain no hardware
initialization, raw Flash API, security, semaphore, or linker implementation.

`boot_service_abi.h` is the stable function-pointer boundary between the
Flash-resident core and the RAM-resident Flash service lib.

`BootAlgorithm_Run` returns `BootAlgorithmAction` only after the matching OK
response has been sent. The product outer layer performs the real jump/reset.
Use `BootAlgorithm_GetPendingEntryPoint()` before handling a Run action.
