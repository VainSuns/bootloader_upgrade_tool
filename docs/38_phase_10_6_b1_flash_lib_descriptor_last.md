# Phase 10.6-B1 flash_lib descriptor/header last-write loading

## Goal

Downloaded flash_service_lib descriptor/header words are written last during
RAM_LOAD.

Before the descriptor words are written, RAM must not contain a valid service
descriptor magic. This prevents either side from treating a partially loaded
service image as ready.

## Implementation

1. Before the formal service RAM_LOAD, the PC sends an independent descriptor
   invalidation RAM_LOAD transaction that writes two zero words at the service
   descriptor address.
2. Service RAM packets are generated with descriptor words removed from the
   address-ordered packet stream.
3. Non-descriptor service image words are sent first.
4. Descriptor/header words are sent last.
5. Ordinary RAM_LOAD behavior is unchanged.
6. App DFU behavior is unchanged.

The descriptor address can still be at the beginning of the image. Only the
write order changes.

The invalidation transaction prevents stale retained RAM contents from exposing
an old valid service descriptor magic while the new service body is being
loaded. It is a separate RAM_LOAD_BEGIN / RAM_LOAD_DATA / RAM_LOAD_END sequence
and is not part of the formal service image.

The invalidation transaction uses the descriptor address as its temporary
RAM_LOAD entry point so existing RAM_LOAD range validation remains unchanged.
This entry point is not used for RUN_RAM and is overwritten by the following
formal service RAM_LOAD.

## CRC rule

The bootloader RAM_LOAD CRC is calculated in receive order, not address order.

Therefore:

```text
descriptor image_crc32
== descriptor-last RAM_LOAD receive-order CRC32
== RAM_CHECK_CRC expected_crc32
== SERVICE_ATTACH expected_crc32
```

`patch_flash_service_image(..., load_order="descriptor_last")` patches the
descriptor image CRC and CRC patch words for this descriptor-last receive order.

The descriptor invalidation words are not included in the formal service image
`total_words`, descriptor `image_crc32`, RAM_CHECK_CRC, or SERVICE_ATTACH
expected CRC. The formal service image CRC remains reproducible from the
descriptor-last receive order only.

## Preserved behavior

1. `service_attach_probe` remains compatible.
2. `service_flash_probe` remains compatible.
3. `RAM_LOAD + RAM_CHECK_CRC + SERVICE_ATTACH + GET_SERVICE_STATUS` still forms
   the service attach flow.
4. Ordinary RAM app loading remains address ordered.

## Deferred

This phase does not implement:

1. GUI wait window.
2. automatic App jump.
3. BOOT_ATTEMPT write policy.
4. APP_CONFIRMED write policy.
5. DSP boot decision integration.
6. RESET command.
7. CPU2 / W5300 / GUI changes.

flash_lib ready detection in DSP startup remains future work.
