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

## Power-loss and execution-policy boundary

Descriptor/record publication is last. An erased, partial, corrupt, or
unpublished record is ignored. Without a valid current IMAGE_VALID the image is
not trusted.

Automatic boot requires the stable `confirmed_bootable` conditions:

- metadata is valid;
- the current IMAGE_VALID is valid;
- the current image has BOOT_ATTEMPT;
- the current image has APP_CONFIRMED;
- its entry point is valid.

PC explicit Flash RUN admission is defined by RAC-V2 and does not require
BOOT_ATTEMPT, APP_CONFIRMED, a current Program Image, or VerifyEvidence.

Current DSP behavior is implementation state, not a competing long-term
authority. If an older DSP rejects explicit RUN without BOOT_ATTEMPT, the PC
must report the real failure. That implementation does not override RAC-V2;
correcting the DSP contract belongs to a separate task.

This document defines journal format and record binding only. It does not
redefine Runtime workflow. Verify does not write IMAGE_VALID, and RUN does not
write BOOT_ATTEMPT.
