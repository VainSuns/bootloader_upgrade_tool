#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# VERSION: phase6_1_fixed_serial_v6_poll_in_waiting
#
# Purpose:
#   Phase 6.1 fixed-data Program/Verify smoke test.
#
# Key point of v6:
#   This version reuses the receive strategy that has already been proven
#   successful by serial_fixed_get_device_info_test.py:
#
#       while not timeout:
#           pending = ser.in_waiting
#           if pending:
#               rx += ser.read(pending)
#
#   It does NOT use read(1) timeout-based magic search.
#
# Serial strategy:
#   - No autobaud.
#   - pyserial directly.
#   - Open with serial.Serial(port=..., timeout=0, write_timeout=1).
#   - After open: set DTR=0, RTS=0 by default.
#   - Delay after open: 0.5s.
#   - Do not clear input by default.
#   - Each request is one serial.write(frame) + flush().
#   - Response is collected by polling in_waiting and parsing buffered bytes.

from __future__ import annotations

import argparse
import sys
import time
from enum import IntEnum
from typing import Iterable, Sequence

import serial


VERSION = "phase6_1_fixed_serial_v6_poll_in_waiting"

MAGIC0 = 0xA55A
MAGIC1 = 0x5AA5
MAGIC_BYTES = bytes.fromhex("5A A5 A5 5A")
HEADER_BYTES = 20

PROTOCOL_VERSION = 0x0001
PACKET_REQUEST = 0x0001
PACKET_RESPONSE = 0x0002
PACKET_ERROR_RESPONSE = 0x0003
STATUS_OK = 0x0000

TARGET_FLASH_APP = 0x0001
SECTOR_B_MASK = 0x00000002
TEST_ADDRESS = 0x00082400

TEST_WORDS = (
    0x1234,
    0x5678,
    0x9ABC,
    0xDEF0,
    0x1111,
    0x2222,
    0x3333,
    0x4444,
)


class Command(IntEnum):
    GET_DEVICE_INFO = 0x0002
    GET_LAST_ERROR = 0x0004
    ERASE = 0x0201
    PROGRAM_BEGIN = 0x0210
    PROGRAM_DATA = 0x0211
    PROGRAM_END = 0x0212
    VERIFY_BEGIN = 0x0220
    VERIFY_DATA = 0x0221
    VERIFY_END = 0x0222


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def words_to_bytes(words: Iterable[int]) -> bytes:
    out = bytearray()
    for word in words:
        word = int(word)
        if word < 0 or word > 0xFFFF:
            raise ValueError(f"word out of uint16 range: {word}")
        out.append(word & 0xFF)
        out.append((word >> 8) & 0xFF)
    return bytes(out)


def bytes_to_words(data: bytes | bytearray) -> list[int]:
    if len(data) % 2 != 0:
        raise ValueError("odd byte count")
    return [data[i] | (data[i + 1] << 8) for i in range(0, len(data), 2)]


def crc16_words(words: Sequence[int]) -> int:
    return crc16_ccitt_false(words_to_bytes(words))


def split_u32(value: int) -> tuple[int, int]:
    return value & 0xFFFF, (value >> 16) & 0xFFFF


def hex_bytes(data: bytes | bytearray) -> str:
    return " ".join(f"{b:02X}" for b in data)


def hex_words(words: Sequence[int]) -> str:
    return "[" + ", ".join(f"0x{w:04X}" for w in words) + "]"


def build_frame(command: int, sequence: int, payload: Sequence[int]) -> bytes:
    payload = tuple(int(x) for x in payload)

    header_no_crc = (
        MAGIC0,
        MAGIC1,
        PROTOCOL_VERSION,
        PACKET_REQUEST,
        int(command),
        int(sequence),
        0x0000,
        0x0000,
        len(payload),
    )

    frame_words = (
        *header_no_crc,
        crc16_words(header_no_crc),
        *payload,
        crc16_words(payload),
    )

    return words_to_bytes(frame_words)


def try_extract_frame(rx: bytearray) -> tuple[int, int, int, int, list[int], bytes] | None:
    pos = bytes(rx).find(MAGIC_BYTES)
    if pos < 0:
        # Keep only possible partial magic tail.
        if len(rx) > 3:
            del rx[:-3]
        return None

    if pos > 0:
        del rx[:pos]

    if len(rx) < HEADER_BYTES:
        return None

    header = bytes(rx[:HEADER_BYTES])
    header_words = bytes_to_words(header)

    expected_header_crc = crc16_words(header_words[:9])
    actual_header_crc = header_words[9]
    if expected_header_crc != actual_header_crc:
        # Drop one byte and keep searching.
        del rx[0]
        return None

    payload_count = header_words[8]
    frame_len = HEADER_BYTES + (payload_count + 1) * 2

    if len(rx) < frame_len:
        return None

    frame = bytes(rx[:frame_len])
    del rx[:frame_len]

    payload_crc_words = bytes_to_words(frame[HEADER_BYTES:])
    payload = payload_crc_words[:-1]

    expected_payload_crc = crc16_words(payload)
    actual_payload_crc = payload_crc_words[-1]
    if expected_payload_crc != actual_payload_crc:
        raise RuntimeError(
            f"bad payload CRC: expected 0x{expected_payload_crc:04X}, got 0x{actual_payload_crc:04X}"
        )

    return (
        header_words[3],
        header_words[4],
        header_words[5],
        header_words[7],
        payload,
        frame,
    )


def collect_response_by_in_waiting(
    ser: serial.Serial,
    timeout_s: float,
    *,
    print_chunks: bool,
) -> tuple[int, int, int, int, list[int], bytes]:
    deadline = time.monotonic() + timeout_s
    rx = bytearray()

    while time.monotonic() < deadline:
        pending = ser.in_waiting
        if pending:
            chunk = ser.read(pending)
            if chunk:
                rx.extend(chunk)
                if print_chunks:
                    print(f"RX_CHUNK({len(chunk)}): {hex_bytes(chunk)}")

                frame = try_extract_frame(rx)
                if frame is not None:
                    return frame

        time.sleep(0.01)

    if rx:
        raise TimeoutError(f"timeout waiting for complete response frame; RX_TOTAL({len(rx)}): {hex_bytes(rx)}")
    raise TimeoutError("timeout waiting for response bytes")


def open_serial(args: argparse.Namespace) -> serial.Serial:
    ser = serial.Serial(
        port=args.port,
        baudrate=args.baud,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=0,
        write_timeout=1,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )

    ser.dtr = bool(args.dtr)
    ser.rts = bool(args.rts)

    print(f"SET DTR={int(bool(args.dtr))}")
    print(f"SET RTS={int(bool(args.rts))}")

    if args.delay_after_open > 0:
        print(f"DELAY after open: {args.delay_after_open:.3f}s")
        time.sleep(args.delay_after_open)

    if args.clear_input:
        print("CLEAR input buffer")
        ser.reset_input_buffer()

    if args.clear_output:
        print("CLEAR output buffer")
        ser.reset_output_buffer()

    return ser


def transact(
    ser: serial.Serial,
    command: Command,
    seq: int,
    payload: Sequence[int],
    timeout_s: float,
    *,
    print_chunks: bool,
) -> list[int]:
    frame = build_frame(int(command), seq, payload)
    label = command.name

    print(f"PROTO: TX {label} seq={seq}: {hex_bytes(frame)}")

    written = ser.write(frame)
    ser.flush()

    if written is not None and written != len(frame):
        raise RuntimeError(f"{label}: serial.write wrote {written}/{len(frame)} bytes")

    packet_type, rx_command, rx_seq, status, rx_payload, raw = collect_response_by_in_waiting(
        ser,
        timeout_s,
        print_chunks=print_chunks,
    )

    print(f"PROTO: RX {label}: {hex_bytes(raw)}")
    print(
        f"PARSE: packet_type=0x{packet_type:04X}, "
        f"command=0x{rx_command:04X}, sequence={rx_seq}, "
        f"status=0x{status:04X}, payload_words={len(rx_payload)}"
    )

    if rx_command != int(command):
        raise RuntimeError(f"{label}: command mismatch, expected 0x{int(command):04X}, got 0x{rx_command:04X}")

    if rx_seq != seq:
        raise RuntimeError(f"{label}: sequence mismatch, expected {seq}, got {rx_seq}")

    if packet_type not in (PACKET_RESPONSE, PACKET_ERROR_RESPONSE):
        raise RuntimeError(f"{label}: invalid packet_type=0x{packet_type:04X}")

    if status != STATUS_OK:
        raise RuntimeError(f"{label}: status=0x{status:04X}, payload={hex_words(rx_payload)}")

    return rx_payload


def erase_payload() -> list[int]:
    low, high = split_u32(SECTOR_B_MASK)
    return [low, high, 0x0000]


def begin_payload() -> list[int]:
    total_low, total_high = split_u32(len(TEST_WORDS))
    entry_low, entry_high = split_u32(TEST_ADDRESS)

    return [
        TARGET_FLASH_APP,
        0x0001,
        total_low,
        total_high,
        entry_low,
        entry_high,
        0x0000,
        0x0000,
        0x0000,
    ]


def data_payload() -> list[int]:
    addr_low, addr_high = split_u32(TEST_ADDRESS)

    return [
        addr_low,
        addr_high,
        len(TEST_WORDS),
        0x0000,
        0x0000,
        *TEST_WORDS,
    ]


def end_payload() -> list[int]:
    total_low, total_high = split_u32(len(TEST_WORDS))
    return [0x0001, 0x0000, total_low, total_high, 0x0000, 0x0000]


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 6.1 fixed serial smoke test v6")
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--erase-timeout", type=float, default=60.0)
    parser.add_argument("--delay-after-open", type=float, default=0.5)
    parser.add_argument("--dtr", type=int, choices=(0, 1), default=0)
    parser.add_argument("--rts", type=int, choices=(0, 1), default=0)
    parser.add_argument("--clear-input", action="store_true")
    parser.add_argument("--clear-output", action="store_true")
    parser.add_argument("--quiet-rx-chunks", action="store_true")
    parser.add_argument("--device-info-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    try:
        print(f"VERSION: {VERSION}")
        print(f"Opening {args.port} @ {args.baud} without autobaud")
        print("Precondition: DSP is already waiting for normal protocol frames.")

        with open_serial(args) as ser:
            seq = 1
            print_chunks = not args.quiet_rx_chunks

            device_info = transact(
                ser,
                Command.GET_DEVICE_INFO,
                seq,
                [],
                args.timeout,
                print_chunks=print_chunks,
            )
            print(f"DeviceInfo payload: {hex_words(device_info)}")
            seq += 1

            if args.device_info_only:
                print("PASS: GET_DEVICE_INFO test succeeded")
                return 0

            if args.verify_only:
                print("Mode: verify-only")
                transact(ser, Command.VERIFY_BEGIN, seq, begin_payload(), args.timeout, print_chunks=print_chunks)
                seq += 1
                transact(ser, Command.VERIFY_DATA, seq, data_payload(), args.timeout, print_chunks=print_chunks)
                seq += 1
                transact(ser, Command.VERIFY_END, seq, end_payload(), args.timeout, print_chunks=print_chunks)
                print("PASS: verify-only succeeded")
                return 0

            print("Mode: erase + program + verify")
            transact(ser, Command.ERASE, seq, erase_payload(), args.erase_timeout, print_chunks=print_chunks)
            seq += 1

            transact(ser, Command.PROGRAM_BEGIN, seq, begin_payload(), args.timeout, print_chunks=print_chunks)
            seq += 1
            transact(ser, Command.PROGRAM_DATA, seq, data_payload(), args.timeout, print_chunks=print_chunks)
            seq += 1
            transact(ser, Command.PROGRAM_END, seq, end_payload(), args.timeout, print_chunks=print_chunks)
            seq += 1

            transact(ser, Command.VERIFY_BEGIN, seq, begin_payload(), args.timeout, print_chunks=print_chunks)
            seq += 1
            transact(ser, Command.VERIFY_DATA, seq, data_payload(), args.timeout, print_chunks=print_chunks)
            seq += 1
            transact(ser, Command.VERIFY_END, seq, end_payload(), args.timeout, print_chunks=print_chunks)

            print("PASS: Phase 6.1 Program/Verify smoke test succeeded")
            return 0

    except TimeoutError as exc:
        print(f"TIMEOUT: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"FAILED: {exc!r}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
