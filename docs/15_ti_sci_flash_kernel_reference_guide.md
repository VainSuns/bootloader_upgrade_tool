# 15 TI SCI Flash Kernel Reference Guide for Codex

## 1. Positioning

This guide summarizes the TI SCI flash kernel example as a **simple official reference case**.

It is **not** a general engineering solution. Codex may borrow ideas from this case, but must not fully imitate its project structure, global state design, packet style, or module boundaries.

The current project defines its own upper-layer bootloader architecture and protocol.

## 2. What to learn from TI example

Codex may reference:

- SCI boot / flash kernel high-level flow;
- host sends kernel or data stream;
- boot stream uses key / entry point / block address / block length / block data model;
- flash write uses buffered data;
- erase / program / verify / run / reset functional concepts.

## 3. SCI boot / flash kernel flow

Typical TI example flow:

```text
SCI init / autobaud
receive command packet
dispatch command
for DFU/program:
  parse boot stream
  receive blocks
  program Flash
  verify
send ACK/NAK or response
```

Current project changes this:

- autobaud is IO Device connection layer;
- no TI-style ACK/NAK word;
- formal protocol uses frame + CRC + sequence;
- Program replaces Download naming;
- DFU is GUI flow, not DSP command.

## 4. hex2000 boot stream idea

TI boot stream provides the concept of:

```text
entry point
block count / block records
block address
block length
block data
terminator
```

Current project PC side parses `hex2000 -boot -a -sci8` output and converts it into `FirmwareImage`, then sends protocol `ProgramBegin/Data/End`.

## 5. Flash write buffering

TI example buffers incoming words before Flash program. Current project keeps the same idea but defines a Flash-specific protocol rule:

```text
ProgramData / VerifyData data_words must be 8-word multiple.
PC pads Flash tail data with 0xFFFF.
```

RamLoadData is RAM and has no Flash-style 8-word alignment requirement.

## 6. Erase / Program / Verify / Run / Reset model

Borrowed functional model:

- Erase sector；
- Program data；
- Verify data；
- Run entry point；
- Reset device。

Current project differences:

- Erase uses only sector_mask；
- Program is three-stage；
- Verify is three-stage；
- Run/Reset return action after OK response；
- detailed ErrorDetail payload replaces simple ACK/NAK。
