from __future__ import annotations

from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.firmware.models import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.images import (
    ImageIdentity,
    PreparedFlashImage,
    compare_flash_image_with_metadata,
    compare_image_identity_with_metadata,
    prepare_flash_app_image,
    prepare_ram_app_image,
    prepare_service_image,
)
from bootloader_upgrade_tool.protocol.boot_protocol_client import BootProtocolClient
from bootloader_upgrade_tool.protocol.constants import PacketType
from bootloader_upgrade_tool.protocol.frame import Frame
from bootloader_upgrade_tool.protocol.frame_reader import FrameReader
from bootloader_upgrade_tool.protocol.models import MetadataSummary
from bootloader_upgrade_tool.session import UpgradeSession, UpgradeSessionConfig
from bootloader_upgrade_tool.targets import (
    CPU1_PROFILE,
    CPU2_PROFILE,
    AddressRange,
    UnsupportedOperationError,
    require_command,
)
from bootloader_upgrade_tool.transport.serial_transport import SerialTransport, SerialTransportConfig


class MockSerial:
    def __init__(self, responses: list[bytes] | None = None, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.responses = responses or []
        self.writes: list[bytes] = []
        self.flushes = 0
        self.closed = False
        self.dtr = True
        self.rts = True
        self.timeout = None

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        self.flushes += 1

    def read(self, max_bytes: int) -> bytes:
        if not self.responses:
            return b""
        data = self.responses.pop(0)
        if len(data) > max_bytes:
            self.responses.insert(0, data[max_bytes:])
            return data[:max_bytes]
        return data

    def close(self) -> None:
        self.closed = True


def image(block_address: int = 0x082400, entry: int | None = None) -> FirmwareImage:
    return FirmwareImage(
        source_out_file="app.out",
        generated_hex_file="app.txt",
        entry_point=block_address if entry is None else entry,
        blocks=(FirmwareBlock(block_address, (1, 2, 3, 4)),),
        file_checksum="sha256",
        format_info={},
    )


def metadata(**overrides: int) -> MetadataSummary:
    values = dict(
        metadata_valid=1,
        active_slot=1,
        latest_record_type=1,
        boot_attempt_count=0,
        app_confirmed=0,
        boot_attempt_limit=3,
        app_version_major=0,
        app_version_minor=0,
        app_version_patch=0,
        app_version_build=0,
        entry_point=0x082400,
        image_crc32=0x12345678,
        state=0,
        valid_record_count=1,
        invalid_record_count=0,
        erased_record_count=0,
        free_record_count=1,
        next_record_index=1,
        image_size_words=8,
        target_device_id=0x377D,
        target_cpu_id=1,
    )
    values.update(overrides)
    return MetadataSummary(**values)


def test_serial_transport_defaults() -> None:
    config = SerialTransportConfig(port="COM1")
    assert config.baudrate == 9600
    assert config.autobaud_timeout_ms == 5000


def test_serial_transport_autobaud_write_flush_and_short_read(monkeypatch) -> None:
    serial = MockSerial([b"", b"A", b"xy"])
    monkeypatch.setattr("bootloader_upgrade_tool.transport.serial_transport.time.sleep", lambda _: None)
    transport = SerialTransport(
        SerialTransportConfig(port="COM1", rx_timeout_ms=1234),
        serial_factory=lambda **_: serial,
    )

    transport.open()
    transport.write_all(b"hello")

    assert serial.writes[:2] == [b"A", b"A"]
    assert serial.writes[-1] == b"hello"
    assert serial.flushes >= 3
    assert serial.timeout == 1.234
    assert transport.read_some(10) == b"xy"


class ChunkTransport:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    def open(self) -> None: ...
    def close(self) -> None: ...
    def write_all(self, data: bytes) -> None: ...

    def read_some(self, max_bytes: int) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


def test_frame_reader_magic_sync_dirty_discard_and_partial_frame() -> None:
    frame = Frame(PacketType.RESPONSE, 0x0001, 1, (0x1234,)).encode_bytes()
    reader = FrameReader(ChunkTransport([b"\x00\x11", frame[:5], frame[5:]]))

    assert reader.read_frame(timeout_ms=100).payload == (0x1234,)


def test_frame_reader_odd_byte_handling() -> None:
    frame = Frame(PacketType.RESPONSE, 0x0001, 1).encode_bytes()
    reader = FrameReader(ChunkTransport([b"\x5A", b"\xA5\xA5\x5A" + frame[4:]]))

    assert reader.read_frame(timeout_ms=100).command == 0x0001


class RecordingTransport:
    def __init__(self) -> None:
        self.written = b""
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True

    def write_all(self, data: bytes) -> None:
        self.written += data

    def read_some(self, max_bytes: int) -> bytes:
        return b""


class MockFrameReader:
    def read_frame(self, **kwargs: int) -> Frame:
        return Frame(PacketType.RESPONSE, 0x0001, 1, (0xBEEF,))


def test_boot_protocol_client_transact_with_mocked_transport_frame_reader() -> None:
    transport = RecordingTransport()
    client = BootProtocolClient(transport, MockFrameReader())  # type: ignore[arg-type]

    assert client.transact(0x0001) == (0xBEEF,)
    assert transport.written.startswith(b"\x5A\xA5\xA5\x5A")


def test_upgrade_session_connect_disconnect() -> None:
    transport = RecordingTransport()
    session = UpgradeSession(UpgradeSessionConfig(transport))

    session.connect()
    session.disconnect()

    assert transport.opened is True
    assert transport.closed is True
    assert isinstance(session.client, BootProtocolClient)


def test_address_range_contains() -> None:
    item = AddressRange(10, 20)
    assert item.contains(10)
    assert not item.contains(20)
    assert item.contains_range(12, 4)
    assert not item.contains_range(18, 3)


def test_profiles_and_require_command() -> None:
    assert CPU1_PROFILE.name
    assert CPU2_PROFILE.name
    assert require_command(CPU1_PROFILE.command_set, "ping") == 0x0001
    with pytest.raises(UnsupportedOperationError):
        require_command(CPU2_PROFILE.command_set, "erase")


def test_prepare_flash_app_image_uses_target_memory_map(monkeypatch) -> None:
    import bootloader_upgrade_tool.images.flash_image as module

    monkeypatch.setattr(module, "load_firmware_image", lambda *a, **k: (image(), "app.txt"))

    prepared = prepare_flash_app_image("app.out", target=CPU1_PROFILE)

    assert prepared.sector_mask & CPU1_PROFILE.memory_map.flash.metadata_sector_mask  # type: ignore[union-attr]
    assert prepared.identity.entry_point == 0x082400


def test_load_firmware_image_hides_temporary_sci8_path(monkeypatch, tmp_path) -> None:
    import bootloader_upgrade_tool.images.models as module

    monkeypatch.setattr(module, "run_hex2000", lambda source, output, **kwargs: output.write_text("ok"))
    monkeypatch.setattr(module, "build_firmware_image", lambda source, output: image())

    loaded, generated = module.load_firmware_image(tmp_path / "app.out")

    assert loaded.entry_point == 0x082400
    assert generated is None


def test_prepare_ram_app_image_uses_target_memory_map(monkeypatch) -> None:
    import bootloader_upgrade_tool.images.ram_image as module

    monkeypatch.setattr(module, "load_firmware_image", lambda *a, **k: (image(0x008000), "ram.txt"))

    prepared = prepare_ram_app_image("ram.out", target=CPU1_PROFILE)

    assert prepared.entry_point == 0x008000
    assert prepared.total_words == 4


def test_prepare_service_image_uses_target_map_and_stores_required_capabilities(monkeypatch) -> None:
    import bootloader_upgrade_tool.images.service_image as module

    service = image(0x010000)
    symbols = SimpleNamespace(
        descriptor_address=0x010000,
        api_table_address=0x010010,
        crc_patch_address=0x010020,
    )
    monkeypatch.setattr(module, "load_firmware_image", lambda *a, **k: (service, "service.txt"))
    monkeypatch.setattr(module, "parse_flash_service_symbols_from_map", lambda *a, **k: symbols)
    monkeypatch.setattr(module, "patch_flash_service_image", lambda image, **k: image)
    monkeypatch.setattr(module, "calculate_service_ram_load_crc32_descriptor_last", lambda *a, **k: 0xCAFE)

    prepared = prepare_service_image("service.out", "service.map", target=CPU1_PROFILE, required_capabilities=3)

    assert prepared.required_capabilities == 3
    assert prepared.expected_crc32 == 0xCAFE


def test_image_metadata_comparison_cases() -> None:
    identity = ImageIdentity(0x082400, 8, 0x12345678, 0x082408)

    assert compare_image_identity_with_metadata(identity, metadata(metadata_valid=0)).reason == "METADATA_INVALID"
    assert compare_image_identity_with_metadata(identity, metadata(entry_point=1)).mismatches == ("entry_point",)
    assert compare_image_identity_with_metadata(identity, metadata(image_size_words=9)).mismatches == ("image_size_words",)
    assert compare_image_identity_with_metadata(identity, metadata(image_crc32=1)).mismatches == ("image_crc32",)
    assert compare_image_identity_with_metadata(identity, metadata()).same_image is True


def test_compare_flash_image_with_metadata_uses_identity() -> None:
    prepared = PreparedFlashImage(
        image=image(),
        identity=ImageIdentity(0x082400, 8, 0x12345678, 0xDEADBEEF),
        sector_mask=2,
    )

    assert compare_flash_image_with_metadata(prepared, metadata()).same_image is True
