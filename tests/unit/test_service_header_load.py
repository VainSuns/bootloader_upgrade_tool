from bootloader_upgrade_tool.core.workflow import UpgradeWorkflow
from bootloader_upgrade_tool.firmware import crc32_words
from bootloader_upgrade_tool.firmware.service_image import (
    calculate_service_ram_load_crc32,
    patch_flash_service_image,
    prepare_service_ram_packets,
)
from bootloader_upgrade_tool.protocol.constants import (
    SERVICE_ABI_MAJOR,
    SERVICE_ABI_MINOR,
    SERVICE_REQUIRED_CAPABILITIES,
    ServiceState,
)
from bootloader_upgrade_tool.protocol.models import DeviceInfo, ServiceStatus
from test_service_image_patch import HEADER, image, symbols


def test_packets_are_address_ordered_and_include_immutable_fill() -> None:
    patched = patch_flash_service_image(image(), symbols=symbols())
    packets = prepare_service_ram_packets(patched, 8)
    transmitted = tuple(word for packet in packets for word in packet.words)

    assert [packet.address for packet in packets] == sorted(packet.address for packet in packets)
    assert any(word == 0xFFFF for packet in packets for word in packet.words)
    assert sum(map(lambda packet: len(packet.words), packets)) == patched.total_words
    assert calculate_service_ram_load_crc32(patched, 8) == crc32_words(transmitted)


class FakeClient:
    def __init__(self, expected_crc32: int, expected_total_words: int) -> None:
        self.device_info = DeviceInfo(0x377D, 1, 0, 1, 0, 1, 0, 64, 8, 1, 1, 3, 0)
        self.expected_crc32 = expected_crc32
        self.expected_total_words = expected_total_words
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __getattr__(self, name: str):
        if name == "get_service_status":
            def status(**kwargs: object) -> ServiceStatus:
                self.calls.append((name, kwargs))
                return ServiceStatus(
                    ServiceState.ATTACHED, SERVICE_ABI_MAJOR, SERVICE_ABI_MINOR, 0, 0,
                    int(SERVICE_REQUIRED_CAPABILITIES), 0,
                    self.expected_crc32, self.expected_total_words,
                )
            return status
        def call(**kwargs: object) -> None:
            self.calls.append((name, kwargs))
        return call


def test_load_and_attach_service_has_no_separate_invalidation() -> None:
    patched = patch_flash_service_image(image(), symbols=symbols())
    expected_crc = calculate_service_ram_load_crc32(patched, 8)
    client = FakeClient(expected_crc, patched.total_words)

    status = UpgradeWorkflow(client).load_and_attach_service(patched, HEADER)

    assert status.service_state == ServiceState.ATTACHED
    assert client.calls[0][0] == "ram_load_begin"
    data_calls = [call for call in client.calls if call[0] == "ram_load_data"]
    assert [call[1]["address"] for call in data_calls] == sorted(call[1]["address"] for call in data_calls)
    assert client.calls[-2] == (
        "service_attach",
        {
            "header_address": HEADER,
            "expected_crc32": expected_crc,
            "expected_total_words": patched.total_words,
            "timeout_ms": 10_000,
        },
    )
    assert client.calls[-1][0] == "get_service_status"
