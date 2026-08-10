# Metadata Journal Contract

## Ownership and Flash layout

This document is the sole authority for Slot A metadata layout, record validity, binding, scanning, and power-loss publication semantics. Wire payloads are defined in [communication_protocol.md](communication_protocol.md); write admission and sequencing are defined in [pc_operations.md](pc_operations.md).

The Flash-resident bootloader reads metadata. Only the downloaded Flash Service writes it through controlled append operations. Application program/verify ranges exclude the metadata area.

Slot A metadata occupies C28x word addresses `0x082000..0x0823FF`; the application occupies `0x082400..0x0BFFFF`. The journal has 16 append-only records of 64 words. Erased words are `0xFFFF`.

## Record format and CRC

A record contains identity/publication fields, type, slot and image binding, sequence/attempt information, reserved fields, and a trailing CRC. It is usable only when its magic, version, fixed 64-word length, supported type, slot/range fields, entry point, reserved-field rules, and record CRC are valid.

The record CRC is CRC32/IEEE over words 0 through 61, processing each 16-bit word low byte first and then high byte. Words 62 and 63 store the CRC. The final publication fields are written last so erased, partial, corrupt, or unpublished records are ignored after power loss.

The bound image CRC covers actual padded application words in address order, including PC-added `0xFFFF` alignment padding. It excludes metadata, unwritten address gaps, and unused Flash.

## Record types and binding

The journal defines three record types:

- IMAGE_VALID binds Slot A, entry point, image size/end, and image CRC.
- BOOT_ATTEMPT copies the current IMAGE_VALID identity and records an attempt for that image.
- APP_CONFIRMED copies the current IMAGE_VALID identity and confirms that image after at least one bound BOOT_ATTEMPT.

A new IMAGE_VALID starts a new lifecycle. BOOT_ATTEMPT and APP_CONFIRMED records bound to an older image cannot be reused for the new image. Verify does not append IMAGE_VALID, and RUN does not append BOOT_ATTEMPT; those are separate PC operations.

## Scan semantics

The scanner examines physical journal order, rejects invalid or ambiguous records, selects the current valid IMAGE_VALID, and derives only subsequent BOOT_ATTEMPT and APP_CONFIRMED relationships whose complete image identity matches it. Equal or ambiguous newest-sequence state is not automatically trusted.

`GET_METADATA_SUMMARY` is the parsed metadata view. Generic MEMORY_READ may inspect raw memory for diagnostics but does not provide metadata semantics and never mutates the journal.

## Publication and automatic boot

Append-only, descriptor-last publication ensures interruption leaves either the prior valid state or an ignorable incomplete record. A missing current IMAGE_VALID means the image is not trusted.

The metadata relationship required for `confirmed_bootable` is:

```text
valid journal state
AND current IMAGE_VALID is valid
AND a BOOT_ATTEMPT is bound to that image
AND APP_CONFIRMED is bound to that image
AND the bound entry point is valid
```

The DSP boot policy that consumes this relationship is defined in [dsp_bootloader.md](dsp_bootloader.md). Explicit RUN admission is separate and is defined in [pc_operations.md](pc_operations.md).
