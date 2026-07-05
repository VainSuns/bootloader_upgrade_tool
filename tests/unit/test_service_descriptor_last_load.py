from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage, crc32_words
from bootloader_upgrade_tool.firmware.service_image import (
    calculate_service_ram_load_crc32_descriptor_last,
    patch_flash_service_image,
    prepare_service_ram_packets_descriptor_last,
)
from bootloader_upgrade_tool.core.workflow import UpgradeWorkflow
from bootloader_upgrade_tool.protocol.constants import (
    SERVICE_REQUIRED_CAPABILITIES,
    SERVICE_DESCRIPTOR_MAGIC,
    SERVICE_DESCRIPTOR_WORDS,
    ServiceState,
)
from bootloader_upgrade_tool.protocol.models import DeviceInfo, ServiceStatus, join_u32


BASE = 0x010000
DESCRIPTOR = BASE
CRC_PATCH = BASE + SERVICE_DESCRIPTOR_WORDS
API = BASE + SERVICE_DESCRIPTOR_WORDS + 2


def image() -> FirmwareImage:
    return FirmwareImage(
        source_out_file="service.out",
        generated_hex_file="service.txt",
        entry_point=BASE,
        blocks=(FirmwareBlock(BASE, tuple(range(96))),),
        file_checksum="fixture",
        format_info={},
    )


def words_at(firmware: FirmwareImage, address: int, count: int) -> tuple[int, ...]:
    block = next(block for block in firmware.blocks if block.address <= address < block.end_exclusive)
    offset = address - block.address
    return block.words[offset : offset + count]


def test_descriptor_packets_are_sent_last() -> None:
    patched = patch_flash_service_image(
        image(),
        descriptor_address=DESCRIPTOR,
        api_table_address=API,
        crc_patch_address=CRC_PATCH,
        load_order="descriptor_last",
        max_data_words=8,
    )
    packets = prepare_service_ram_packets_descriptor_last(
        patched, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS, max_data_words=8
    )

    descriptor_packets = [
        packet
        for packet in packets
        if packet.address < DESCRIPTOR + SERVICE_DESCRIPTOR_WORDS
        and packet.address + len(packet.words) > DESCRIPTOR
    ]

    assert descriptor_packets
    assert packets[-len(descriptor_packets) :] == tuple(descriptor_packets)
    assert all(
        packet.address >= DESCRIPTOR + SERVICE_DESCRIPTOR_WORDS
        or packet.address + len(packet.words) <= DESCRIPTOR
        for packet in packets[: -len(descriptor_packets)]
    )
    assert sum(len(packet.words) for packet in packets) == patched.total_words


def test_descriptor_last_crc_matches_descriptor_and_patch_words() -> None:
    patched = patch_flash_service_image(
        image(),
        descriptor_address=DESCRIPTOR,
        api_table_address=API,
        crc_patch_address=CRC_PATCH,
        load_order="descriptor_last",
        max_data_words=8,
    )
    descriptor = words_at(patched, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS)
    final_crc = calculate_service_ram_load_crc32_descriptor_last(
        patched, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS, max_data_words=8
    )

    assert join_u32(descriptor[0], descriptor[1]) == SERVICE_DESCRIPTOR_MAGIC
    assert join_u32(descriptor[14], descriptor[15]) == final_crc
    assert join_u32(descriptor[18], descriptor[19]) == crc32_words(descriptor[:18])
    assert words_at(patched, CRC_PATCH, 2) != (0, 0)


def test_address_order_patch_remains_available() -> None:
    patched = patch_flash_service_image(
        image(),
        descriptor_address=DESCRIPTOR,
        api_table_address=API,
        crc_patch_address=CRC_PATCH,
    )
    descriptor = words_at(patched, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS)
    assert join_u32(descriptor[0], descriptor[1]) == SERVICE_DESCRIPTOR_MAGIC


class FakeClient:
    def __init__(self, expected_crc32: int, expected_total_words: int) -> None:
        self.device_info = DeviceInfo(0x377D, 1, 0, 1, 0, 1, 0, 64, 8, 1, 1, 3, 0)
        self.expected_crc32 = expected_crc32
        self.expected_total_words = expected_total_words
        self.calls: list[tuple[str, dict[str, object]]] = []

    def ram_load_begin(self, **kwargs: object) -> None:
        self.calls.append(("ram_load_begin", kwargs))

    def ram_load_data(self, **kwargs: object) -> None:
        self.calls.append(("ram_load_data", kwargs))

    def ram_load_end(self, **kwargs: object) -> None:
        self.calls.append(("ram_load_end", kwargs))

    def ram_check_crc(self, **kwargs: object) -> None:
        self.calls.append(("ram_check_crc", kwargs))

    def service_attach(self, **kwargs: object) -> None:
        self.calls.append(("service_attach", kwargs))

    def get_service_status(self, **kwargs: object) -> ServiceStatus:
        self.calls.append(("get_service_status", kwargs))
        return ServiceStatus(
            ServiceState.ATTACHED,
            1,
            0,
            0,
            1,
            int(SERVICE_REQUIRED_CAPABILITIES),
            0,
            self.expected_crc32,
            self.expected_total_words,
        )


def test_load_and_attach_service_invalidates_stale_descriptor_magic_first() -> None:
    patched = patch_flash_service_image(
        image(),
        descriptor_address=DESCRIPTOR,
        api_table_address=API,
        crc_patch_address=CRC_PATCH,
        load_order="descriptor_last",
        max_data_words=8,
    )
    formal_packets = prepare_service_ram_packets_descriptor_last(
        patched, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS, max_data_words=8
    )
    formal_total_words = sum(len(packet.words) for packet in formal_packets)
    formal_crc = calculate_service_ram_load_crc32_descriptor_last(
        patched, DESCRIPTOR, SERVICE_DESCRIPTOR_WORDS, max_data_words=8
    )
    client = FakeClient(formal_crc, formal_total_words)

    status = UpgradeWorkflow(client).load_and_attach_service(patched, DESCRIPTOR)

    invalidate_crc = crc32_words((0, 0))
    assert status.service_state == ServiceState.ATTACHED
    assert client.calls[:3] == [
        (
            "ram_load_begin",
            {
                "packet_count": 1,
                "total_words": 2,
                "entry_point": DESCRIPTOR,
                "image_crc32": invalidate_crc,
                "timeout_ms": 10_000,
            },
        ),
        (
            "ram_load_data",
            {
                "address": DESCRIPTOR,
                "words": (0, 0),
                "packet_index": 0,
                "timeout_ms": 10_000,
            },
        ),
        (
            "ram_load_end",
            {
                "packet_count": 1,
                "total_words": 2,
                "image_crc32": invalidate_crc,
                "timeout_ms": 10_000,
            },
        ),
    ]

    formal_begin = client.calls[3]
    assert formal_begin[0] == "ram_load_begin"
    assert formal_begin[1]["total_words"] == patched.total_words
    assert formal_begin[1]["total_words"] == formal_total_words
    assert formal_begin[1]["image_crc32"] == formal_crc

    formal_data_calls = [
        call for call in client.calls[4:] if call[0] == "ram_load_data"
    ]
    descriptor_calls = [
        call
        for call in formal_data_calls
        if int(call[1]["address"]) < DESCRIPTOR + SERVICE_DESCRIPTOR_WORDS
        and int(call[1]["address"]) + len(call[1]["words"]) > DESCRIPTOR
    ]
    assert descriptor_calls
    assert formal_data_calls[-len(descriptor_calls) :] == descriptor_calls

    assert ("ram_check_crc", {
        "expected_crc32": formal_crc,
        "expected_total_words": formal_total_words,
        "timeout_ms": 10_000,
    }) in client.calls
    assert ("service_attach", {
        "descriptor_address": DESCRIPTOR,
        "expected_crc32": formal_crc,
        "expected_total_words": formal_total_words,
        "timeout_ms": 10_000,
    }) in client.calls
