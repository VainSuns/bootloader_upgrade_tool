# Phase 10.7 CPU1 Hardware Validation Record

## Scope

This is historical hardware evidence for TMS320F28377D CPU1 over SCI/RS232 at
commit `3cf0670cf0e54e39f6bb2c885910d607051c909c`. It is not a current workflow,
protocol, GUI, or Runtime V2 authority. Where behavior differs from current
contracts, the current contract and source take precedence.

## Observed hardware results

The recorded run passed service attach/reuse, application-area erase, program,
verify, metadata append, RUN, confirmation, force-reflash, and Sector A safety
rejection checks. Raw log archives were reviewed separately and were not
committed.

Notable observations at that commit:

- the service was attached after a forced reload and then reused when status,
  CRC, word count, ABI, and capabilities matched;
- the metadata-sharing sector was erased before remaining application sectors;
- low-level Program did not write IMAGE_VALID or send RUN;
- Sector A erase/program requests were rejected before Flash access;
- APP_CONFIRMED was not reused after a new IMAGE_VALID lifecycle.

## Interpretation boundary

Historical CLI combinations in this record do not define the current product
workflow. In particular, current operation contracts keep Verify separate from
IMAGE_VALID and RUN separate from BOOT_ATTEMPT. CPU1-specific masks and sector
facts are target-profile/Flash-layout evidence, not shared GUI widget defaults.
