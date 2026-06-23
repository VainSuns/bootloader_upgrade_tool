# 16 F28377D Flash Operation Guide for Codex

## 1. Scope

Codex does not implement the low-level TI F021 Flash API port, but must understand what the user implementation needs and what constraints affect bootloader algorithm design.

## 2. Required TI F021 items

Typical user implementation uses:

```c
#include "F021_F2837xD_C28x.h"
```

Important calls:

```c
Fapi_initializeAPI()
Fapi_setActiveFlashBank()
Fapi_issueAsyncCommandWithAddress()
Fapi_issueProgrammingCommand()
Fapi_checkFsmForReady()
Fapi_getFsmStatus()
Fapi_doBlankCheck()
Fapi_doVerify()
Fapi_flushPipeline()
```

For F2837xD, use `Fapi_FlashBank0`.

## 3. RAM execution rule

During erase/program, the CPU must not fetch code or constants from the Flash bank being operated on. Wrapper, caller chain, busy wait loop, and error path must be RAM-safe.

## 4. Erase model

```text
Fapi_issueAsyncCommandWithAddress(Fapi_EraseSector, sectorAddress)
wait Fapi_checkFsmForReady()
read Fapi_getFsmStatus()
Fapi_doBlankCheck()
```

Success requires API success, FMSTAT zero, BlankCheck success.

## 5. Program model

Use AutoECC:

```text
Fapi_issueProgrammingCommand(..., Fapi_AutoEccGeneration)
wait Fapi_checkFsmForReady()
read Fapi_getFsmStatus()
verify
```

## 6. Verify model

Use `Fapi_doVerify()` and preserve first failing address/status.

## 7. Alignment

C28x:

```text
64-bit  = 4 x 16-bit words
128-bit = 8 x 16-bit words
```

Current protocol requires all ProgramData / VerifyData / RamLoadData data blocks to be 8-word multiples. This supports Flash alignment, reduces partial AutoECC hazards, keeps RAM-load transfers consistent with the protocol, and simplifies future RAM service lib handling.

## 8. AutoECC constraints

Critical:

- missing data is treated as `0xFFFF`;
- once ECC is programmed for a 64-bit block, that block must not be programmed again before erase;
- do not partially program a 64-bit block and complete later.

## 9. Error propagation

`BootFlashResult` should be a lightweight result code, not a large returned structure.

Detailed diagnostic information should be returned through an output parameter such as:

```c
BootFlashErrorInfo *error_info
```

`BootFlashErrorInfo` should preserve:

```text
operation
address
length_words
api_status
fsm_status
extra
```

FAPI status and FMSTAT are detail fields. They should be stored in `BootFlashErrorInfo` and then mapped into protocol `ErrorDetail` when needed. They are not the main protocol status code.

## 10. Forbidden Codex patterns

Codex must not:

- directly call raw F021 API in upper-layer algorithm;
- hide Flash failures as bool;
- auto-retry ProgramData after timeout;
- generate code that implies repeated Flash programming is safe;
- ignore FMSTAT;
- treat Flash program as a simple memory write.
