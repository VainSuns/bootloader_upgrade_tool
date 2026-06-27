#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal fixed-frame GET_DEVICE_INFO serial test.

用途：
    专门排查“第三方串口软件能收到 DSP 返回，但 Python 收不到”的问题。

特点：
    - 不执行 autobaud。
    - 只发送一条固定 GET_DEVICE_INFO 帧。
    - 该帧与你第三方软件验证成功的帧完全一致。
    - 默认不清空 input buffer，避免误清掉已经到达的数据。
    - 打开串口后默认关闭 DTR/RTS。
    - 支持打开后等待。
    - 支持一次性写入或按字节慢速写入。
    - 接收端按超时等待并打印收到的所有原始字节。

运行：
    python tools/serial_fixed_get_device_info_test.py --port COM3

如果仍收不到，试：
    python tools/serial_fixed_get_device_info_test.py --port COM3 --slow-byte-ms 2
    python tools/serial_fixed_get_device_info_test.py --port COM3 --dtr 1 --rts 1
    python tools/serial_fixed_get_device_info_test.py --port COM3 --clear-input
"""

from __future__ import annotations

import argparse
import sys
import time

import serial


GET_DEVICE_INFO_FRAME = bytes.fromhex(
    "5A A5 A5 5A "
    "01 00 "
    "01 00 "
    "02 00 "
    "01 00 "
    "00 00 "
    "00 00 "
    "00 00 "
    "46 5B "
    "FF FF"
)

MAGIC = bytes.fromhex("5A A5 A5 5A")


def hex_bytes(data: bytes | bytearray) -> str:
    return " ".join(f"{b:02X}" for b in data)


def set_line_state(ser: serial.Serial, name: str, value: int | None) -> None:
    if value is None:
        return

    if name == "dtr":
        ser.dtr = bool(value)
    elif name == "rts":
        ser.rts = bool(value)
    else:
        raise ValueError(name)

    print(f"SET {name.upper()}={int(bool(value))}")


def read_available_until_timeout(ser: serial.Serial, timeout_s: float) -> bytes:
    deadline = time.monotonic() + timeout_s
    rx = bytearray()

    while time.monotonic() < deadline:
        pending = ser.in_waiting
        if pending:
            chunk = ser.read(pending)
            if chunk:
                rx.extend(chunk)
                print(f"RX_CHUNK({len(chunk)}): {hex_bytes(chunk)}")

        # 短轮询。这里不用一次 read 很长，避免驱动 timeout 行为差异。
        time.sleep(0.01)

    return bytes(rx)


def parse_first_response(rx: bytes) -> None:
    pos = rx.find(MAGIC)
    if pos < 0:
        print("PARSE: no magic 5A A5 A5 5A found")
        return

    print(f"PARSE: magic found at byte offset {pos}")

    frame = rx[pos:]
    if len(frame) < 20:
        print(f"PARSE: incomplete header, got {len(frame)} bytes after magic")
        return

    words = [frame[i] | (frame[i + 1] << 8) for i in range(0, 20, 2)]
    payload_words = words[8]
    frame_len = (10 + payload_words + 1) * 2

    print(
        "PARSE HEADER: "
        f"protocol=0x{words[2]:04X}, "
        f"packet_type=0x{words[3]:04X}, "
        f"command=0x{words[4]:04X}, "
        f"sequence={words[5]}, "
        f"status=0x{words[7]:04X}, "
        f"payload_words={payload_words}"
    )

    if len(frame) < frame_len:
        print(f"PARSE: incomplete frame, need {frame_len} bytes, got {len(frame)}")
        return

    full = frame[:frame_len]
    print(f"PARSE FRAME({len(full)}): {hex_bytes(full)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal fixed GET_DEVICE_INFO serial test")
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--delay-after-open", type=float, default=0.5)
    parser.add_argument("--slow-byte-ms", type=float, default=0.0)
    parser.add_argument("--clear-input", action="store_true")
    parser.add_argument("--clear-output", action="store_true")
    parser.add_argument("--dtr", type=int, choices=(0, 1), default=0)
    parser.add_argument("--rts", type=int, choices=(0, 1), default=0)
    args = parser.parse_args()

    print(f"OPEN {args.port} @ {args.baud}")

    try:
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
    except Exception as exc:
        print(f"FAILED open serial: {exc!r}", file=sys.stderr)
        return 1

    try:
        set_line_state(ser, "dtr", args.dtr)
        set_line_state(ser, "rts", args.rts)

        if args.delay_after_open > 0:
            print(f"DELAY after open: {args.delay_after_open:.3f}s")
            time.sleep(args.delay_after_open)

        if args.clear_input:
            print("CLEAR input buffer")
            ser.reset_input_buffer()

        if args.clear_output:
            print("CLEAR output buffer")
            ser.reset_output_buffer()

        print(f"TX({len(GET_DEVICE_INFO_FRAME)}): {hex_bytes(GET_DEVICE_INFO_FRAME)}")

        if args.slow_byte_ms > 0:
            delay_s = args.slow_byte_ms / 1000.0
            for b in GET_DEVICE_INFO_FRAME:
                ser.write(bytes([b]))
                ser.flush()
                time.sleep(delay_s)
        else:
            written = ser.write(GET_DEVICE_INFO_FRAME)
            ser.flush()
            print(f"WRITTEN: {written}")

        rx = read_available_until_timeout(ser, args.timeout)

        print(f"RX_TOTAL({len(rx)}): {hex_bytes(rx) if rx else '<empty>'}")
        parse_first_response(rx)

        return 0 if rx else 2

    finally:
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
