# Phase 10.3 RAM_LOAD + RAM_CHECK_CRC + RUN_RAM Evidence

## 1. Summary

| Area | Result | Notes |
|---|---|---|
| Protocol constants | PASS | `RAM_LOAD_BEGIN/DATA/END`, `RAM_CHECK_CRC`, and `RUN_RAM` are defined on PC and DSP. |
| DSP RAM_LOAD handlers | PASS | Host tests compile and pass. |
| PC RAM workflow | PASS | Simulator workflow tests pass. |
| RAM_CHECK_CRC | PASS | CRC32/IEEE over 16-bit words, low byte first. |
| RUN_RAM | PASS | Simulator accepts valid loaded RAM entry after CRC check. |
| Simulator tests | PASS | RAM_LOAD/RAM_CHECK_CRC/RUN_RAM paths covered. |
| Full pytest | PASS | `130 passed in 6.83s`. |
| Hardware RAM_RUN | PENDING | Hardware command template is below. |

## 2. Design Notes

- RAM bootloader is used as a pre-validation carrier before Flash-resident bootloader development.
- Final product direction remains Flash-resident bootloader.
- RUN_RAM is a development-only command for RAM bootloader pre-validation.
- The production Flash-resident bootloader shall not expose RUN_RAM.
- RAM_LOAD does not use Flash API.
- RUN_RAM does not write metadata.
- No Flash 8-word alignment is required for RAM_LOAD.
- RUN_RAM requires a successful RAM_CHECK_CRC after RAM_LOAD.
- For Phase 10.3, RUN_RAM uses the same allowed RAM write-region policy as
  RAM_LOAD. No separate executable RAM allowlist is maintained.
- The entry point must still be inside the loaded RAM image range and pass RAM
  range validation.
- PC/simulator RAM write ranges: BEGIN `[0x000000,0x000002)`,
  RAMM0 usable `[0x000123,0x000400)`, RAMLS/RAMD `[0x008000,0x00C000)`,
  RAMGS candidate `[0x010000,0x01BFF8)`, CPU message RAM
  `[0x03F800,0x040000)`, CANA `[0x049000,0x049800)`, CANB
  `[0x04B000,0x04B800)`.
- DSP hardware RAM permission uses generated `boot_user_ram_limit.h`.

## 3. Automated Test Evidence

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_simulator_workflow.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_metadata_probe.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_ram_run.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_dsp_host.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Result:

```text
tests/unit/test_ram_run.py:
4 passed in 0.09s

tests/unit/test_simulator_workflow.py:
48 passed in 0.22s

tests/unit/test_metadata_probe.py:
9 passed in 0.07s

tests/unit/test_dsp_host.py:
3 passed in 0.73s

Full pytest:
130 passed in 6.83s
```

## 4. Simulator ram_run Evidence

Unit-level simulator smoke is implemented in `tests/unit/test_ram_run.py`.

Manual smoke command:

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool.tools.ram_run --transport simulator --image $env:TEMP\ram_run_smoke.sci8.txt
```

Result:

```text
PASS: RAM image loaded, CRC checked, and RUN_RAM accepted
Entry point: 0x00008000
Total words: 3
CRC32: 0x5E813FB2
Packet count: 1
```

## 5. Hardware RAM_RUN Evidence

Manual command:

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool.tools.ram_run --transport serial --port COM10 --baud 9600 --image path\to\ram_app.out
```

Template:

- Target:
- COM:
- Baud:
- RAM app:
- Entry point:
- RAM_CHECK_CRC:
- RUN_RAM:
- Observable marker / behavior:
- Result:

Expected:

```text
HW-RAM-01 Connect + DeviceInfo: PASS
HW-RAM-02 RAM_LOAD: PASS
HW-RAM-03 RAM_CHECK_CRC: PASS
HW-RAM-04 RUN_RAM: PASS
Entry point: 0x________
Total words: ________
CRC32: 0x________
Observable result: marker/GPIO/loop observed
```

## 6. Closure Decision

```text
PASS WITH HARDWARE PENDING: automated RAM_LOAD/RAM_CHECK_CRC/RUN_RAM validation passes; hardware RAM_RUN evidence remains pending.
```
