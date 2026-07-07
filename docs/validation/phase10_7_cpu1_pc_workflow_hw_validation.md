# Phase 10.7 CPU1 PC Workflow Hardware Validation

## Summary

Phase 10.7 CPU1 PC workflow content optimization / tool split validation is complete.

Result:

```text
PASS
```

Validated commit:

```text
3cf0670cf0e54e39f6bb2c885910d607051c909c
feat(pc): split cpu1_upgrade flash workflow commands
```

Validation scope:

```text
TMS320F28377D CPU1
SCI/RS232 transport
CPU1 Flash App upgrade workflow
Downloaded flash_service_lib
PC cpu1_upgrade CLI
```

This validation record intentionally does not commit raw hardware log ZIP files. Raw logs were reviewed separately and summarized here.

---

## Software Validation

Software-side checks passed before hardware validation:

```text
py_compile: PASS
tests/unit/test_cpu1_upgrade_cli.py: 41 passed
full pytest: 223 passed
scoped git diff --check: PASS
```

---

## Hardware Validation Result

Hardware validation was performed on TMS320F28377D CPU1 through SCI/RS232.

| Item | Result |
|---|---|
| Initial status read | PASS |
| SERVICE_ATTACH with forced reload | PASS |
| SERVICE_ATTACH reuse | PASS |
| Low-level erase full mask | PASS |
| Status after erase | PASS |
| Low-level program App only | PASS |
| Status after program | PASS |
| Low-level verify App + IMAGE_VALID write | PASS |
| Status after verify | PASS |
| flash same_image skip | PASS |
| flash --force | PASS |
| Status after flash --force | PASS |
| run first BOOT_ATTEMPT | PASS |
| Status after run | PASS |
| upgrade warning direct-run | PASS |
| confirm APP_CONFIRMED | PASS |
| Status after confirm | PASS |
| upgrade confirmed direct-run | PASS |
| upgrade --force resets confirmation state | PASS |
| Status after upgrade --force | PASS |
| final confirm | PASS |
| final status | PASS |
| erase Sector A safety rejection | PASS |
| flash Sector A safety rejection | PASS |

---

## Key Observations

### Service attach and reuse

The forced attach path completed successfully:

```text
service.reused = false
service.attach_performed = true
service.service_state = ATTACHED
```

The immediate reuse path completed successfully:

```text
service.reused = true
service.attach_performed = false
service.service_state = ATTACHED
```

This confirms that `cpu1_upgrade` can safely reuse an already attached `flash_service_lib` when `GET_SERVICE_STATUS` reports matching state, loaded image CRC32, loaded word count, ABI, and required capabilities.

---

### Low-level erase

The low-level erase command with full Slot A mask behaved as expected:

```text
requested_mask = 0x00003FFE
erased_masks   = [0x00000002, 0x00003FFC]
```

This confirms:

```text
metadata sector is erased first
remaining requested sectors are erased second
metadata sector is not erased twice
Sector A / bootloader is not erased
```

---

### Low-level program

The low-level program command programmed the App only.

Confirmed behavior:

```text
program.programmed = true
IMAGE_VALID was not written
BOOT_ATTEMPT was not written
APP_CONFIRMED was not written
RUN was not sent
```

The status after program still reported no valid image metadata, which confirms that `program` does not commit `IMAGE_VALID`.

---

### Low-level verify

The low-level verify command verified the App and then wrote `IMAGE_VALID`.

Confirmed behavior:

```text
verify.verified = true
verify.image_valid_written = true
metadata_valid = 1
BOOT_ATTEMPT = 0
APP_CONFIRMED = 0
preview.reason = FIRST_TRIAL_REQUIRES_PC_RUN
```

This confirms that `verify` is intentionally defined as:

```text
VERIFY_APP + COMMIT_IMAGE_VALID
```

---

### flash workflow

The same-image skip path behaved correctly:

```text
action = skipped
reason = IMAGE_VALID_ALREADY_MATCHES_INPUT
service = null
image_valid_written = false
```

The forced flash path behaved correctly:

```text
action = flashed
image_valid_written = true
erased_masks = [0x00000002, app_remaining_mask]
```

This confirms that `flash` preserves the required ordering:

```text
metadata sector first
remaining App sectors second
program
verify
write IMAGE_VALID
```

---

### run and BOOT_ATTEMPT

The first `run` after `IMAGE_VALID` wrote `BOOT_ATTEMPT` and sent `RUN`:

```text
boot_attempt_written = true
run_sent = true
```

After re-entering bootloader, metadata showed:

```text
BOOT_ATTEMPT exists
APP_CONFIRMED = 0
preview.reason = WAIT_APP_CONFIRM
```

This confirms that first trial boot remains PC-mediated and unconfirmed Apps are not automatically booted.

---

### upgrade warning direct-run

The same-image, attempted-but-unconfirmed path behaved correctly:

```text
action = skipped
service = null
boot_attempt_written = false
run_sent = true
warning.code = BOOT_ATTEMPT_WITHOUT_APP_CONFIRMED
app_confirm = pending / not verified
```

This confirms that `upgrade` does not reload service or rewrite `BOOT_ATTEMPT` when the current image already has a boot attempt but no confirmation.

---

### confirm

The `confirm` command successfully wrote `APP_CONFIRMED`:

```text
APP_CONFIRMED = 1
preview.reason = APP_CONFIRMED
```

The command did not send `RUN`.

The intended confirm order is:

```text
GET_METADATA_SUMMARY
require current IMAGE_VALID
require BOOT_ATTEMPT for current IMAGE_VALID
ensure_service_attached
write APP_CONFIRMED
GET_METADATA_SUMMARY
verify APP_CONFIRMED
```

---

### confirmed direct-run

The same-image, already-confirmed path behaved correctly:

```text
action = skipped
service = null
boot_attempt_written = false
run_sent = true
app_confirm = already confirmed
warning = null
```

This confirms that confirmed images can be directly run without reattaching service or rewriting metadata.

---

### upgrade --force

The forced upgrade path reset confirmation state correctly:

```text
action = flashed
image_valid_written = true
boot_attempt_written = true
run_sent = true
app_confirm = pending / not verified
```

After re-entering bootloader:

```text
BOOT_ATTEMPT exists
APP_CONFIRMED = 0
preview.reason = WAIT_APP_CONFIRM
```

This confirms that old `APP_CONFIRMED` records are not reused after a forced reflash / new `IMAGE_VALID` write.

---

### Safety rejection

Sector A / bootloader erase attempts were rejected before real Flash operations:

```text
ok = false
stage = SAFETY_CHECK
error_code = SAFETY_ERROR
message contains Sector A / bootloader
```

This confirms that local safety-check failures are no longer misclassified as `PROTOCOL_ERROR`.

---

## Final Board State

After final confirm, the board ended in confirmed bootable state:

```text
metadata_valid = 1
IMAGE_VALID valid
BOOT_ATTEMPT exists for current IMAGE_VALID
APP_CONFIRMED exists for current IMAGE_VALID
preview.reason = APP_CONFIRMED
```

Expected bootloader behavior after this state:

```text
The bootloader may automatically jump to the confirmed App after the PC GUI preemption window expires.
```

---

## Conclusion

Phase 10.7 CPU1 PC workflow content optimization is validated.

Validated features:

```text
service attach force
service attach reuse
low-level erase
low-level program
low-level verify + IMAGE_VALID
flash same_image skip
flash --force
run first BOOT_ATTEMPT
upgrade warning direct-run
confirm APP_CONFIRMED
confirmed direct-run
upgrade --force confirmation reset
final confirmed bootable state
Sector A safety rejection with SAFETY_ERROR
```

Conclusion:

```text
Phase 10.7 CPU1 PC workflow is ready for GUI integration planning.
```
