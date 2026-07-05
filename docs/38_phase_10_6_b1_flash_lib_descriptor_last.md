# Phase 10.6-B1 flash_lib descriptor/header last-write loading

## Goal

Downloaded flash_service_lib descriptor/header words are written last during
RAM_LOAD.

Before the descriptor words are written, RAM must not contain a valid service
descriptor magic. This prevents either side from treating a partially loaded
service image as ready.

## Implementation

1. Service RAM packets are generated with descriptor words removed from the
   address-ordered packet stream.
2. Non-descriptor service image words are sent first.
3. Descriptor/header words are sent last.
4. Ordinary RAM_LOAD behavior is unchanged.
5. App DFU behavior is unchanged.

The descriptor address can still be at the beginning of the image. Only the
write order changes.

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
