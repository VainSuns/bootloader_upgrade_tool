# App Slot Metadata Journal Contract

## Purpose and authority

This document records the current Slot A metadata format and stable journal
semantics. Protocol command and payload details remain authoritative in
`14_communication_protocol.md`; PC sequencing remains authoritative in the
operation-library contract.

## Ownership and layout

The Flash-resident bootloader reads metadata. The downloaded Flash service
performs metadata writes through the controlled append operation. Application
program/verify ranges exclude the metadata area.

Current Slot A metadata occupies `0x082000..0x0823FF`; the application area is
`0x082400..0x0BFFFF`. The journal contains 16 records of 64 words. Records are
append-only; erased words are `0xFFFF`. Partially written or invalid records are
ignored.

## Record types

The implemented record types are:

```text
IMAGE_VALID
BOOT_ATTEMPT
APP_CONFIRMED
```

They form an ordered lifecycle for the current image. Verify does not append
IMAGE_VALID, and RUN does not append BOOT_ATTEMPT; the PC operation library
exposes those writes separately.

## Record validation

A record is usable only when its magic, version, 64-word length, record type,
slot/range fields, entry point, and record CRC are valid. Record CRC uses
CRC32/IEEE over words 0..61, processing each word low byte first, then high
byte. Words 62..63 contain the CRC.

The image CRC covers actual padded application words in address order,
including PC-added `0xFFFF` alignment padding. It excludes metadata, unwritten
gaps, and unused Flash.

The scan selects valid records in physical journal order and derives the latest
IMAGE_VALID, subsequent BOOT_ATTEMPT count, and any subsequent APP_CONFIRMED.
Equal/ambiguous newest sequence state is not automatically trusted.

## Current metadata operations

- IMAGE_VALID binds entry point, image size, CRC, application end, and Slot A.
- BOOT_ATTEMPT copies the current IMAGE_VALID identity and may be appended until
  the advertised limit, capped by the operation library at three.
- APP_CONFIRMED copies the current IMAGE_VALID identity and requires at least
  one current BOOT_ATTEMPT.
- A new IMAGE_VALID begins a new lifecycle; older attempts/confirmation do not
  confirm the new image.

`GET_METADATA_SUMMARY` is the normal parsed view. `FLASH_READ` is a bounded raw
read primitive for diagnostics and does not mutate metadata.

## Power-loss rule

Descriptor/record publication is last. An erased, partial, corrupt, or
unpublished record is ignored. Without a valid current IMAGE_VALID the image is
not trusted. Exact automatic-boot and explicit-RUN policy is governed by the
current DSP implementation and RAC-V2; this format document does not redefine
RUN sequencing.
