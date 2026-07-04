# Phase 10.4 Downloaded flash_service_lib Evidence

## 1. Summary

| Area | Result | Notes |
|---|---|---|
| Protocol commands | PASS | Added `GET_SERVICE_STATUS` (`0x0007`) and `SERVICE_ATTACH` (`0x0008`). |
| Service descriptor | PASS | Fixed 20-word descriptor layout with magic/version/ABI/API/range/CRC/capability checks. |
| PC workflow | PASS | External image patching, then `RAM_LOAD + RAM_CHECK_CRC + SERVICE_ATTACH + GET_SERVICE_STATUS`. |
| Simulator attach | PASS | Success path, negative attach cases, and service-gated Flash routing covered by unit tests. |
| CCS service image skeleton | PASS | Added source-controlled CPU1 RAMGS executable project skeleton. |
| Erase/Program/Verify through service | PASS | Simulator workflow still passes after attach. |
| Full pytest | PASS | `152 passed`. |
| Hardware service attach | PENDING | Target-board service attach not executed in this patch. |

## 2. Design Notes

- RAM bootloader is a pre-validation carrier.
- Final product direction remains Flash-resident bootloader.
- Downloaded `flash_service_lib` is not run with `RUN_RAM`.
- Bootloader remains in control after `SERVICE_ATTACH`.
- Flash commands are dispatched through the attached `BootServiceApi`.
- Existing static service attachment remains available for host/debug tests to avoid disrupting earlier Phase 10.2 and 10.3 coverage.
- Codex provides source support and PC patching only; the user builds the real service binary externally and provides the linker map for symbol extraction.

## Phase 10.4-1 External flash_service_lib Image Patch Flow

1. Codex generates source-code support only.
2. User builds actual `flash_service_lib.out` externally.
3. PC tool parses descriptor/API/CRC-patch addresses from the linker map.
4. PC tool patches descriptor and CRC correction words.
5. `SERVICE_ATTACH` uses the patched image.
6. Simulator service-gated validation passed.
7. Hardware `SERVICE_ATTACH` remains pending.

Future hardware command template:

```powershell
.\.venv\Scripts\python.exe -m bootloader_upgrade_tool.tools.service_attach_probe `
  --transport serial `
  --port COM10 `
  --baud 9600 `
  --image path\to\flash_service_lib_cpu01.out `
  --map path\to\flash_service_lib_cpu01.map `
  --hex2000 E:\CodeComposerStudio\CCS12.7\ccs\tools\compiler\ti-cgt-c2000_22.6.1.LTS\bin
```

The map must contain `g_boot_flash_service_descriptor`,
`g_boot_flash_service_crc_patch`, and `g_boot_flash_service_api`.
`g_boot_flash_service_descriptor` and `g_boot_flash_service_crc_patch` must not
be reported as `UNINITIALIZED` in the linker map, and their address ranges must
appear in the parsed `FirmwareImage` blocks so the PC patcher can overwrite
them before `RAM_LOAD`.

## Phase 10.4-2 flash_service_lib CPU1 RAMGS CCS Project Skeleton

Added source-controlled project support only:

```text
dsp/flash_service_lib/cpu01/flash_service_lib_cpu01.projectspec
dsp/flash_service_lib/cpu01/flash_service_lib_cpu01_ramgs_lnk.cmd
dsp/flash_service_lib/cpu01/main_flash_service_cpu01.c
dsp/flash_service_lib/cpu01/README.md
```

Fixed RAMGS7-RAMGS9 layout:

```text
descriptor: 0x013000
crc patch : 0x013014
api table : 0x013020
code start: 0x013080
image end : 0x016000
```

The project is a CCS executable project skeleton for an externally built
`flash_service_lib_cpu1.out`. No `.out`, `.map`, `.obj`, `.lib`, generated hex,
or generated text artifact was created by Codex.

CCS import/build and hardware `SERVICE_ATTACH` remain user-side pending.

## Phase 10.4-2B Linker Map Address Ownership

1. `.cmd` owns fixed placement.
2. C source only uses `DATA_SECTION` names.
3. No C header contains absolute service addresses.
4. User builds `.out` and `.map` in CCS.
5. PC tool parses `.map` automatically.
6. User does not manually enter descriptor/API/CRC-patch addresses.
7. Descriptor and CRC-patch symbols are `const` initialized data and must not
   appear as `UNINITIALIZED` in the linker map.
8. Descriptor and CRC-patch address ranges must be present in `FirmwareBlock`
   data after `hex2000` conversion.
9. Hardware `SERVICE_ATTACH` remains pending.

## 3. Protocol Layout

`SERVICE_ATTACH` request payload is 7 words:

```text
0-1 descriptor_address
2-3 expected_crc32
4-5 expected_total_words
6   flags, reserved, must be 0
```

`GET_SERVICE_STATUS` response payload is 12 words:

```text
0   service_state
1   abi_major
2   abi_minor
3   service_major
4   service_minor
5-6 capabilities
7   last_attach_status
8-9 loaded_image_crc32
10-11 loaded_image_words
```

Service descriptor layout is 20 words:

```text
0-1  descriptor_magic
2    descriptor_version
3    descriptor_words
4    abi_major
5    abi_minor
6    service_major
7    service_minor
8-9  api_table_address
10-11 image_start
12-13 image_end_exclusive
14-15 image_crc32
16-17 capabilities
18-19 descriptor_crc32 over words 0..17
```

## 4. Automated Test Evidence

Executed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_service_image_patch.py tests/unit/test_service_attach.py tests/unit/test_dsp_host.py -q
```

Result:

```text
19 passed
```

Phase 10.4-2 regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_dsp_host.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_service_image_patch.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_service_attach.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Result:

```text
3 passed
5 passed
11 passed
152 passed
```

Phase 10.4-2B no-entry-point regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_flash_service_project_skeleton.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_ti_map_symbols.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_service_image_patch.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_service_attach.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_dsp_host.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Result:

```text
2 passed
4 passed
5 passed
11 passed
3 passed
152 passed
```

Additional required regression commands before hardware closure:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_simulator_workflow.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_ram_run.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_metadata_probe.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_dsp_host.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Full suite result:

```text
152 passed
```

## 5. Simulator Evidence

Covered cases:

1. `GET_SERVICE_STATUS` initially reports detached.
2. `SERVICE_ATTACH` rejects before `RAM_LOAD`.
3. `SERVICE_ATTACH` rejects before `RAM_CHECK_CRC`.
4. `SERVICE_ATTACH` rejects bad descriptor address.
5. `SERVICE_ATTACH` rejects expected CRC mismatch.
6. `SERVICE_ATTACH` rejects expected total word mismatch.
7. `SERVICE_ATTACH` rejects bad descriptor magic.
8. `SERVICE_ATTACH` rejects ABI major mismatch.
9. `SERVICE_ATTACH` rejects missing required capability.
10. Successful attach reports service version and capabilities.
11. Erase / Program / Verify still pass after attach.
12. Attach does not set `RUN_RAM` pending action.
13. In service-gated mode, Erase / Program / Verify fail before attach and pass after attach.

## 6. Hardware Evidence Template

```text
HW-SVC-01 Connect + DeviceInfo: PASS / FAIL
HW-SVC-02 RAM_LOAD flash_service_lib: PASS / FAIL
HW-SVC-03 RAM_CHECK_CRC: PASS / FAIL
HW-SVC-04 SERVICE_ATTACH: PASS / FAIL
HW-SVC-05 GET_SERVICE_STATUS attached: PASS / FAIL
HW-SVC-06 Erase through attached service: PASS / FAIL
HW-SVC-07 Program through attached service: PASS / FAIL
HW-SVC-08 Verify through attached service: PASS / FAIL
```

## 7. Closure Decision

PASS WITH HARDWARE PENDING.

No hardware `SERVICE_ATTACH` test was executed in this patch.
