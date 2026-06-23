from collections import deque

import pytest

from bootloader_upgrade_tool.io import IoDeviceNotOpenError, IoTimeoutError, SerialIoDevice


class FakeSerial:
    def __init__(self, *, autobaud_reply: bool = True, **kwargs) -> None:
        self.kwargs = kwargs
        self.autobaud_reply = autobaud_reply
        self.timeout = 0
        self.read_bytes: deque[int] = deque()
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if data == b"A" and self.autobaud_reply:
            self.read_bytes.append(ord("A"))
        return len(data)

    def read(self, size: int) -> bytes:
        return bytes(self.read_bytes.popleft() for _ in range(min(size, len(self.read_bytes))))

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_serial_device_contains_autobaud_and_little_endian_words() -> None:
    created: list[FakeSerial] = []

    def factory(**kwargs):
        port = FakeSerial(**kwargs)
        created.append(port)
        return port

    device = SerialIoDevice("COM7", baudrate=230400, serial_factory=factory)
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
        "COM1", serial_factory=lambda **kwargs: FakeSerial(autobaud_reply=False, **kwargs)
    )
    with pytest.raises(IoDeviceNotOpenError):
        device.read_word(1)
    device.open()
    with pytest.raises(IoTimeoutError, match="autobaud"):
        device.wait_slave(2)
    with pytest.raises(IoTimeoutError, match="word read"):
        device.read_word(2)


def test_serial_device_rejects_non_word_values() -> None:
    device = SerialIoDevice("COM1", serial_factory=lambda **kwargs: FakeSerial(**kwargs))
    device.open()
    with pytest.raises(ValueError, match="uint16"):
        device.write_word(0x10000)
