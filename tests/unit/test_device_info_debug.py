from collections import deque

import pytest

from bootloader_upgrade_tool.core import ProtocolClient
from bootloader_upgrade_tool.io import IoTimeoutError
from bootloader_upgrade_tool.protocol import DeviceInfo
from bootloader_upgrade_tool.protocol.constants import Command


REQUEST = bytes.fromhex(
    "5A A5 A5 5A 01 00 01 00 02 00 01 00 00 00 00 00 00 00 46 5B FF FF"
)
RESPONSE = bytes.fromhex(
    "5A A5 A5 5A 01 00 02 00 02 00 01 00 00 00 00 00 10 00 AA 5D "
    "7D 37 01 00 00 00 01 00 00 00 01 00 00 00 00 00 00 01 F8 00 "
    "01 00 01 00 03 00 00 00 2F 52 30 00 5A AF"
)


class DebugDevice:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.rx: deque[int] = deque()
        self.writes: list[bytes] = []

    def input_bytes_pending(self) -> int:
        return len(self.rx)

    def clear_input(self) -> None:
        self.rx.clear()

    def write_bytes(self, data: bytes) -> int:
        self.writes.append(data)
        self.rx.extend(self.response)
        return len(data)

    def read_byte(self, timeout_ms: int) -> int:
        raise AssertionError("ProtocolClient must use read_available() for receive")

    def read_available(self) -> bytes:
        data = bytes(self.rx)
        self.rx.clear()
        return data


@pytest.mark.parametrize("prefix", (b"", b"\x99"))
def test_get_device_info_debug_sends_golden_request_and_decodes_response(prefix) -> None:
    device = DebugDevice(prefix + RESPONSE)
    result = ProtocolClient(device).get_device_info_debug(timeout_ms=10)

    assert result.request_bytes == REQUEST
    assert result.request_words == [
        0xA55A, 0x5AA5, 1, 1, 2, 1, 0, 0, 0, 0x5B46, 0xFFFF
    ]
    assert result.bytes_written == 22
    assert result.flush_done
    assert result.rx_bytes == prefix + RESPONSE
    assert result.error_stage is None
    assert result.device_info is not None
    assert result.device_info.device_id == 0x377D
    assert result.device_info.cpu_id == 1
    assert result.device_info.max_payload_words == 256
    assert result.device_info.max_data_words == 248
    assert result.device_info.revision_id == 3
    assert result.device_info.uid_unique == 0x0030522F
    assert device.writes == [REQUEST]


def test_get_device_info_debug_reports_no_response_bytes() -> None:
    result = ProtocolClient(DebugDevice(b"")).get_device_info_debug(timeout_ms=10)

    assert result.rx_bytes == b""
    assert result.error_stage == "waiting_for_response"
    assert result.error_message == (
        "No response bytes received after writing and flushing request."
    )


def test_normal_transact_uses_complete_frame_and_byte_resync() -> None:
    device = DebugDevice(b"\x99" + RESPONSE)
    client = ProtocolClient(device)
    traces: list[tuple[str, bytes]] = []
    client.trace_bytes = lambda label, data: traces.append((label, data))

    payload = client.transact(Command.GET_DEVICE_INFO, timeout_ms=10)

    assert device.writes == [REQUEST]
    assert DeviceInfo.from_words(payload).device_id == 0x377D
    assert traces == [
        ("TX GET_DEVICE_INFO seq=1", REQUEST),
        ("RX GET_DEVICE_INFO", b"\x99" + RESPONSE),
    ]


def test_normal_transact_timeout_reports_tx_and_empty_rx() -> None:
    client = ProtocolClient(DebugDevice(b""))
    traces: list[tuple[str, bytes]] = []
    client.trace_bytes = lambda label, data: traces.append((label, data))

    with pytest.raises(IoTimeoutError) as exc:
        client.transact(Command.ERASE, (1, 0, 0), timeout_ms=10)

    assert "ERASE response timed out after 10 ms" in str(exc.value)
    assert "TX bytes: 5A A5 A5 5A" in str(exc.value)
    assert "RX bytes: <empty>" in str(exc.value)
    assert traces[0][0] == "TX ERASE seq=1"
    assert traces[1] == ("RX ERASE timeout", b"")
