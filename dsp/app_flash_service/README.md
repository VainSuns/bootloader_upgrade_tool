# App Flash Service integration

Add `dsp/app_flash_service/src/boot_flash_service_app.c` to the App project and
configure these include paths:

```text
dsp/app_flash_service/include
dsp/flash_service_contract/include
```

## Recommended use

```c
#include "boot_flash_service_app.h"

uint16_t status;

status = BootFlashServiceApp_ConfirmCurrentImage();

if (status == BOOT_FLASH_SERVICE_APP_STATUS_OK)
{
    /* Current image confirmed. */
}
else if (status == BOOT_FLASH_SERVICE_APP_STATUS_UNAVAILABLE)
{
    /* Retained Flash Service is unavailable. */
}
else
{
    /* Flash Service returned a confirmation failure status. */
}
```

`BootFlashServiceApp_ConfirmCurrentImage()` checks Publish State internally.
Other Flash Service status codes pass through unchanged; the App may log or
handle any nonzero status itself. The App does not need the complete Bootloader
protocol header. `BootFlashServiceApp_IsAvailable()` remains available for
status display, pre-call flow decisions, diagnostics, or logging.

The App owner chooses when Confirm occurs.

## Use contract

- Every product boot must pass through the Bootloader first.
- Before the first trial run, the current `IMAGE_VALID` must already have a
  corresponding `BOOT_ATTEMPT`.
- The App must not overwrite Flash Service RAM before Confirm.
- Confirm runs through the function exported by Flash Service; this helper does
  not implement metadata rules.
- After Confirm returns, the App may reuse Flash Service RAM.
- Automatic startup of a confirmed App after later resets does not depend on a
  retained service.
- The App must not call App Export directly while Flash Service is unavailable.
- CPU2 is outside this Batch.

## Address governance

C addresses are defined centrally by `boot_flash_service_layout.h`. The linker
command file currently retains a numeric mirror, and host tests verify that the
two layouts match. This Batch does not change linker-command preprocessing or
CCS linker configuration. App Export and Publish State definitions are governed
centrally by `boot_flash_service_app_contract.h`. The PC continues to treat the
final map as the authority.
