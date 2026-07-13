from __future__ import annotations

from threading import Barrier, Event, Lock, Thread
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
from bootloader_upgrade_tool.core.client import ProtocolDecodeError
from bootloader_upgrade_tool.protocol.boot_protocol_client import (
    BOOTSTRAP_MAX_PAYLOAD_WORDS,
    BootProtocolClient,
    ProtocolInfo,
    ProtocolPayloadLimitError,
)
from bootloader_upgrade_tool.protocol.constants import Command, PacketType
from bootloader_upgrade_tool.protocol.frame import Frame
from bootloader_upgrade_tool.protocol.frame_reader import FrameReader
from bootloader_upgrade_tool.protocol.models import DeviceInfo, MetadataSummary
from bootloader_upgrade_tool.session import UpgradeSession, UpgradeSessionConfig
from bootloader_upgrade_tool.targets import (
    CPU1_PROFILE,
    CPU2_PROFILE,
    AddressRange,
    UnsupportedOperationError,
    require_command,
)
from bootloader_upgrade_tool.transport.serial_transport import SerialTransport, SerialTransportConfig
from bootloader_upgrade_tool.transport.base import TransportError


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


def test_serial_transport_close_retries_same_serial_object() -> None:
    serial = MockSerial()
    calls = 0

    def close() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("busy")

    serial.close = close
    transport = SerialTransport(SerialTransportConfig(port="COM1"), serial_factory=lambda **_: serial)
    transport._serial = serial
    with pytest.raises(TransportError, match="busy"):
        transport.close()
    assert transport._serial is serial
    transport.close()
    assert calls == 2 and transport._serial is None


def test_serial_transport_open_cleanup_failure_retains_serial_for_retry(monkeypatch) -> None:
    serial = MockSerial()
    close_calls = 0
    serial.write = lambda _data: (_ for _ in ()).throw(OSError("autobaud failed"))

    def close() -> None:
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            raise OSError("cleanup failed")

    serial.close = close
    monkeypatch.setattr("bootloader_upgrade_tool.transport.serial_transport.time.sleep", lambda _: None)
    transport = SerialTransport(SerialTransportConfig(port="COM1"), serial_factory=lambda **_: serial)
    with pytest.raises(TransportError, match="autobaud failed.*cleanup failed"):
        transport.open()
    assert transport._serial is serial
    transport.close()
    assert close_calls == 2 and transport._serial is None


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
        self.write_calls: list[bytes] = []
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True

    def write_all(self, data: bytes) -> None:
        self.write_calls.append(data)
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


class QueuedFrameReader:
    def __init__(self, responses: list[Frame]) -> None:
        self.responses = responses
        self.calls: list[dict[str, int]] = []

    def read_frame(self, **kwargs: int) -> Frame:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def protocol_words(max_payload_words: int = 64, **overrides: int) -> tuple[int, ...]:
    values = {
        "protocol_ver": 1,
        "min_supported_ver": 1,
        "max_supported_ver": 1,
        "header_words": 10,
        "crc_type": 1,
        "endian": 1,
        "max_payload_words": max_payload_words,
        "flags": 0,
    }
    values.update(overrides)
    return tuple(values.values())


def capability_info(
    *,
    device_id: int = 0x377D,
    cpu_id: int = 1,
    kernel_ver_minor: int = 0,
    feature_flags: int = 0,
    protocol_ver: int = 1,
    max_payload_words: int = 64,
    max_data_words: int = 16,
) -> DeviceInfo:
    return DeviceInfo(
        device_id, cpu_id, 1, kernel_ver_minor, 0, protocol_ver, feature_flags,
        max_payload_words, max_data_words, 2, 2,
    )


def test_capability_responses_are_cached_once_and_limits_are_negotiated() -> None:
    device = capability_info(max_payload_words=64)
    reader = QueuedFrameReader([
        Frame(PacketType.RESPONSE, Command.GET_DEVICE_INFO, 1, device.to_words()),
        Frame(PacketType.RESPONSE, Command.GET_PROTOCOL_INFO, 2, protocol_words(21)),
    ])
    client = BootProtocolClient(RecordingTransport(), reader)  # type: ignore[arg-type]

    assert client.get_device_info() is client.device_info
    assert client.get_protocol_info() is client.protocol_info
    assert client.effective_max_payload_words == 21
    assert client.effective_max_data_words == 16
    assert client.effective_max_write_data_words == 16


def test_capability_parse_or_compatibility_failure_preserves_cache() -> None:
    old = capability_info()
    reader = QueuedFrameReader([
        Frame(PacketType.RESPONSE, Command.GET_DEVICE_INFO, 1, old.to_words()),
        Frame(PacketType.RESPONSE, Command.GET_DEVICE_INFO, 2, (1, 2)),
    ])
    client = BootProtocolClient(RecordingTransport(), reader)  # type: ignore[arg-type]
    assert client.get_device_info() is old or client.device_info == old
    cached = client.device_info
    with pytest.raises(ProtocolDecodeError):
        client.get_device_info()
    assert client.device_info is cached

    incompatible_device = capability_info(protocol_ver=2)
    reader = QueuedFrameReader([
        Frame(PacketType.RESPONSE, Command.GET_DEVICE_INFO, 1, incompatible_device.to_words()),
        Frame(PacketType.RESPONSE, Command.GET_PROTOCOL_INFO, 2, protocol_words()),
    ])
    client = BootProtocolClient(RecordingTransport(), reader)  # type: ignore[arg-type]
    client.get_device_info()
    with pytest.raises(ProtocolDecodeError, match="do not match"):
        client.get_protocol_info()
    assert client.device_info == incompatible_device and client.protocol_info is None

    old_protocol = ProtocolInfo.from_words(protocol_words())
    reader = QueuedFrameReader([Frame(PacketType.RESPONSE, Command.GET_PROTOCOL_INFO, 1, (1, 2))])
    client = BootProtocolClient(RecordingTransport(), reader)  # type: ignore[arg-type]
    client._protocol_info = old_protocol
    with pytest.raises(ProtocolDecodeError):
        client.get_protocol_info()
    assert client.protocol_info is old_protocol


def test_same_target_device_info_refresh_replaces_non_identity_fields() -> None:
    original = capability_info()
    refreshed = capability_info(kernel_ver_minor=7, feature_flags=3, max_payload_words=32, max_data_words=8)
    reader = QueuedFrameReader([
        Frame(PacketType.RESPONSE, Command.GET_DEVICE_INFO, 1, original.to_words()),
        Frame(PacketType.RESPONSE, Command.GET_DEVICE_INFO, 2, refreshed.to_words()),
    ])
    client = BootProtocolClient(RecordingTransport(), reader)  # type: ignore[arg-type]
    client.get_device_info()
    protocol_info = ProtocolInfo.from_words(protocol_words())
    client._protocol_info = protocol_info

    assert client.get_device_info() == refreshed
    assert client.protocol_info is protocol_info


@pytest.mark.parametrize(
    "received",
    [capability_info(device_id=0x1234), capability_info(cpu_id=2)],
)
def test_same_connection_device_info_identity_change_is_rejected(received) -> None:
    original = capability_info()
    reader = QueuedFrameReader([
        Frame(PacketType.RESPONSE, Command.GET_DEVICE_INFO, 1, original.to_words()),
        Frame(PacketType.RESPONSE, Command.GET_DEVICE_INFO, 2, received.to_words()),
    ])
    client = BootProtocolClient(RecordingTransport(), reader)  # type: ignore[arg-type]
    client.get_device_info()
    protocol_info = ProtocolInfo.from_words(protocol_words())
    client._protocol_info = protocol_info

    with pytest.raises(ProtocolDecodeError, match="cached device_id=.*received device_id"):
        client.get_device_info()
    assert client.device_info == original
    assert client.protocol_info is protocol_info


@pytest.mark.parametrize(
    "words",
    [
        protocol_words(0),
        protocol_words(protocol_ver=2),
        protocol_words(min_supported_ver=2),
        protocol_words(max_supported_ver=0),
        protocol_words(header_words=9),
        protocol_words(crc_type=2),
        protocol_words(endian=2),
    ],
)
def test_protocol_info_rejects_invalid_or_unsupported_values(words) -> None:
    with pytest.raises(ProtocolDecodeError):
        ProtocolInfo.from_words(words)


def negotiated_client(reader: QueuedFrameReader | None = None) -> tuple[BootProtocolClient, RecordingTransport, QueuedFrameReader]:
    transport = RecordingTransport()
    reader = reader or QueuedFrameReader([])
    client = BootProtocolClient(transport, reader)  # type: ignore[arg-type]
    client._device_info = capability_info(max_payload_words=24, max_data_words=16)
    client._protocol_info = ProtocolInfo.from_words(protocol_words(17))
    return client, transport, reader


def test_payload_limits_reject_before_io_without_consuming_sequence() -> None:
    reader = QueuedFrameReader([Frame(PacketType.RESPONSE, Command.PING, 1)])
    client, transport, reader = negotiated_client(reader)
    assert client.transact(Command.PING, (0,) * 17) == ()
    written = transport.written
    calls = len(reader.calls)
    sequence = client._sequence

    with pytest.raises(ProtocolPayloadLimitError) as caught:
        client.transact(Command.PING, (0,) * 18)
    assert caught.value.actual_payload_words == 18
    assert caught.value.effective_max_payload_words == 17
    assert transport.written == written
    assert len(reader.calls) == calls
    assert client._sequence == sequence


def test_effective_data_limits_deduct_overhead_and_align_only_flash() -> None:
    client, _, _ = negotiated_client()
    assert client.effective_max_payload_words == 17
    assert client.effective_max_data_words == 12
    assert client.effective_max_write_data_words == 8

    client._protocol_info = ProtocolInfo.from_words(protocol_words(24))
    assert client.effective_max_payload_words == 24


def test_bootstrap_and_negotiated_response_limits() -> None:
    reader = QueuedFrameReader([Frame(PacketType.RESPONSE, Command.PING, 1)])
    client = BootProtocolClient(RecordingTransport(), reader)  # type: ignore[arg-type]
    client.ping()
    assert reader.calls[0]["max_payload_words"] == BOOTSTRAP_MAX_PAYLOAD_WORDS

    reader = QueuedFrameReader([Frame(PacketType.RESPONSE, Command.PING, 1)])
    client = BootProtocolClient(RecordingTransport(), reader)  # type: ignore[arg-type]
    client._device_info = capability_info(max_payload_words=13, max_data_words=8)
    client.ping()
    assert reader.calls[0]["max_payload_words"] == 13

    reader = QueuedFrameReader([Frame(PacketType.RESPONSE, Command.PING, 1)])
    client, _, reader = negotiated_client(reader)
    client.ping()
    assert reader.calls[0]["max_payload_words"] == 17


def test_non_bootstrap_requires_full_capabilities_before_io() -> None:
    reader = QueuedFrameReader([])
    client = BootProtocolClient(RecordingTransport(), reader)  # type: ignore[arg-type]
    with pytest.raises(ProtocolDecodeError):
        client.transact(Command.ERASE)
    assert client.transport.written == b""
    assert reader.calls == []
    assert client._sequence == 0


def test_reconnect_resets_capabilities_and_next_request_sequence() -> None:
    transport = RecordingTransport()
    session = UpgradeSession(UpgradeSessionConfig(transport))
    session.client.frame_reader = QueuedFrameReader([
        Frame(PacketType.RESPONSE, Command.PING, 1),
        Frame(PacketType.RESPONSE, Command.PING, 1),
    ])  # type: ignore[assignment]
    session.client.ping()
    session.client._device_info = capability_info()
    session.client._protocol_info = ProtocolInfo.from_words(protocol_words())
    session.connect()
    assert session.client.device_info is None
    assert session.client.protocol_info is None
    session.client.ping()
    assert [int.from_bytes(data[10:12], "little") for data in transport.write_calls] == [1, 1]


class SerializingTransport(RecordingTransport):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def write_all(self, data: bytes) -> None:
        self.events.append("write")
        super().write_all(data)


class BlockingFrameReader:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.first_read_started = Event()
        self.release_first_read = Event()
        self._calls = 0
        self._lock = Lock()

    def read_frame(self, **kwargs: int) -> Frame:
        with self._lock:
            self._calls += 1
            call = self._calls
        self.events.append(f"read{call}-start")
        if call == 1:
            self.first_read_started.set()
            assert self.release_first_read.wait(1)
        self.events.append(f"read{call}-end")
        return Frame(PacketType.RESPONSE, Command.PING, call)


def test_complete_transactions_are_serialized() -> None:
    events: list[str] = []
    reader = BlockingFrameReader(events)
    client = BootProtocolClient(SerializingTransport(events), reader)  # type: ignore[arg-type]
    gate = Barrier(3)

    def run() -> None:
        gate.wait()
        client.ping()

    threads = [Thread(target=run), Thread(target=run)]
    for thread in threads:
        thread.start()
    gate.wait()
    assert reader.first_read_started.wait(1)
    reader.release_first_read.set()
    for thread in threads:
        thread.join(1)
        assert not thread.is_alive()
    assert events == ["write", "read1-start", "read1-end", "write", "read2-start", "read2-end"]


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
