from collections import deque
from threading import Event, Thread

import pytest

from bootloader_upgrade_tool.io import (
    IoCancelledError,
    IoDeviceNotOpenError,
    IoTimeoutError,
    SerialIoDevice,
)


class FakeSerial:
    def __init__(self, *, autobaud_reply: bool = True, **kwargs) -> None:
        self.kwargs = kwargs
        self.autobaud_reply = autobaud_reply
        self.timeout = 0
        self.read_bytes: deque[int] = deque()
        self.writes: list[bytes] = []
        self.closed = False
        self.clear_count = 0

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if data == b"A" and self.autobaud_reply:
            self.read_bytes.append(ord("A"))
        return len(data)

    def read(self, size: int) -> bytes:
        return bytes(self.read_bytes.popleft() for _ in range(min(size, len(self.read_bytes))))

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        self.read_bytes.clear()
        self.clear_count += 1

    def close(self) -> None:
        self.closed = True


def test_serial_device_contains_autobaud_and_little_endian_words() -> None:
    created: list[FakeSerial] = []

    def factory(**kwargs):
        port = FakeSerial(**kwargs)
        created.append(port)
        return port

    device = SerialIoDevice(
        "COM7", baudrate=230400, serial_factory=factory, post_autobaud_delay_ms=0
    )
    device.open()
    device.wait_slave(100)
    created[0].read_bytes.extend((0x34, 0x12))

    assert device.read_word(100) == 0x1234
    device.write_word(0xA55A)
    assert created[0].writes == [b"A", bytes((0x5A, 0xA5))]
    assert created[0].kwargs["port"] == "COM7"
    device.close()
    assert created[0].closed


def test_serial_device_requires_open_and_times_out_locally() -> None:
    device = SerialIoDevice(
        "COM1",
        serial_factory=lambda **kwargs: FakeSerial(autobaud_reply=False, **kwargs),
        post_autobaud_delay_ms=0,
    )
    with pytest.raises(IoDeviceNotOpenError):
        device.read_word(1)
    device.open()
    with pytest.raises(IoTimeoutError, match="autobaud"):
        device.wait_slave(2)
    with pytest.raises(IoTimeoutError, match="word read"):
        device.read_word(2)


def test_serial_device_rejects_non_word_values() -> None:
    device = SerialIoDevice(
        "COM1", serial_factory=lambda **kwargs: FakeSerial(**kwargs), post_autobaud_delay_ms=0
    )
    device.open()
    with pytest.raises(ValueError, match="uint16"):
        device.write_word(0x10000)


def test_serial_device_clears_stale_input() -> None:
    created: list[FakeSerial] = []

    def factory(**kwargs):
        port = FakeSerial(**kwargs)
        created.append(port)
        return port

    device = SerialIoDevice("COM10", serial_factory=factory, post_autobaud_delay_ms=0)
    device.open()
    created[0].read_bytes.extend((0x41, 0x41, 0x41))

    device.clear_input()

    assert not created[0].read_bytes
    assert created[0].clear_count == 1
    device.close()


def test_serial_autobaud_can_wait_indefinitely_until_cancelled() -> None:
    device = SerialIoDevice(
        "COM10",
        serial_factory=lambda **kwargs: FakeSerial(autobaud_reply=False, **kwargs),
        post_autobaud_delay_ms=0,
    )
    device.open()
    cancel = Event()
    errors: list[Exception] = []

    def wait() -> None:
        try:
            device.wait_slave(None, cancel)
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=wait)
    thread.start()
    cancel.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert isinstance(errors[0], IoCancelledError)
    device.close()


def test_serial_waits_after_autobaud_before_protocol(monkeypatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr(
        "bootloader_upgrade_tool.io.serial_device.time.sleep", delays.append
    )
    device = SerialIoDevice(
        "COM10",
        serial_factory=lambda **kwargs: FakeSerial(**kwargs),
        post_autobaud_delay_ms=100,
    )
    device.open()

    device.wait_slave(1000)

    assert delays == [0.1]
    device.close()
