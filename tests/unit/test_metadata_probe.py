from dataclasses import asdict
import argparse
import json
from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.operations import (
    MemoryReadRequest,
    OperationErrorInfo,
    OperationResult,
)
from bootloader_upgrade_tool.protocol.constants import BootSlot, MetadataRecordType
from bootloader_upgrade_tool.protocol.models import DeviceInfo, MetadataSummary
from bootloader_upgrade_tool.targets import CPU1_PROFILE
from bootloader_upgrade_tool.tools import metadata_probe
from bootloader_upgrade_tool.transport import TransportOpenResult, TransportOpenStatus


def make_device() -> DeviceInfo:
    return DeviceInfo(
        device_id=0x377D,
        cpu_id=1,
        kernel_ver_major=0,
        kernel_ver_minor=1,
        kernel_ver_patch=0,
        protocol_ver=1,
        feature_flags=0x048F,
        max_payload_words=256,
        max_data_words=248,
        boot_mode=1,
        kernel_layout=1,
        revision_id=3,
        uid_unique=0x0030522F,
    )


def make_summary(
    *,
    latest_record_type: int = 0,
    boot_attempt_count: int = 0,
    entry_point: int = 0,
) -> MetadataSummary:
    return MetadataSummary(
        metadata_valid=1 if latest_record_type else 0,
        active_slot=BootSlot.SLOT_A if latest_record_type else BootSlot.AUTO,
        latest_record_type=latest_record_type,
        boot_attempt_count=boot_attempt_count,
        app_confirmed=0,
        boot_attempt_limit=3,
        app_version_major=1,
        app_version_minor=2,
        app_version_patch=3,
        app_version_build=4,
        entry_point=entry_point,
        image_crc32=0x12345678 if latest_record_type else 0,
        state=1 if latest_record_type else 0,
        valid_record_count=1 if latest_record_type else 0,
        invalid_record_count=0,
        erased_record_count=15,
        free_record_count=15,
        next_record_index=1 if latest_record_type else 0,
        image_size_words=1234 if latest_record_type else 0,
        target_device_id=0x377D if latest_record_type else 0,
        target_cpu_id=1 if latest_record_type else 0,
    )


def session():
    return SimpleNamespace(client=SimpleNamespace(device_info=make_device()))


def operation_result(
    operation: str,
    summary: dict | None = None,
    *,
    details: dict | None = None,
) -> OperationResult:
    return OperationResult(
        True,
        operation,
        CPU1_PROFILE.name,
        operation.upper(),
        summary or {},
        details or {},
    )


def install_operations(monkeypatch, summary: MetadataSummary, words: tuple[int, ...] = ()):
    calls: list[MemoryReadRequest] = []
    monkeypatch.setattr(
        metadata_probe,
        "get_metadata_summary",
        lambda _ctx: operation_result("get_metadata_summary", asdict(summary)),
    )

    def fake_memory_read(_ctx, request):
        calls.append(request)
        return operation_result("memory_read", details={"words": words})

    monkeypatch.setattr(metadata_probe, "memory_read", fake_memory_read)
    return calls


def test_json_formatting_for_blank_metadata_summary(monkeypatch) -> None:
    install_operations(monkeypatch, make_summary())
    result = metadata_probe.collect_probe_result(session(), CPU1_PROFILE)
    data = json.loads(metadata_probe.format_json(result))
    assert data["device"]["target_device_id"] == 0x377D
    assert data["metadata_summary"]["metadata_valid"] is False
    assert data["metadata_summary"]["latest_record_type"] == "NONE"
    assert data["raw_metadata"] is None


def test_json_formatting_for_valid_image_summary(monkeypatch) -> None:
    install_operations(
        monkeypatch,
        make_summary(
            latest_record_type=MetadataRecordType.IMAGE_VALID,
            entry_point=0x082400,
        ),
    )
    result = metadata_probe.collect_probe_result(session(), CPU1_PROFILE)
    data = json.loads(metadata_probe.format_json(result))
    assert data["metadata_summary"]["metadata_valid"] is True
    assert data["metadata_summary"]["latest_record_type"] == "IMAGE_VALID"
    assert data["metadata_summary"]["entry_point"] == 0x082400
    assert data["metadata_summary"]["app_version"] == "1.2.3.4"


def test_text_formatting_and_memory_read_request(monkeypatch) -> None:
    calls = install_operations(
        monkeypatch,
        make_summary(
            latest_record_type=MetadataRecordType.BOOT_ATTEMPT,
            boot_attempt_count=1,
            entry_point=0x082400,
        ),
        (0, 1, 2, 3),
    )
    result = metadata_probe.collect_probe_result(
        session(),
        CPU1_PROFILE,
        metadata_address=0x082020,
        raw_words=4,
    )
    text = metadata_probe.format_text(result)
    assert calls == [MemoryReadRequest(0x082020, 4)]
    assert result.raw_metadata == {"address": 0x082020, "words": [0, 1, 2, 3]}
    assert "latest_record_type: BOOT_ATTEMPT" in text
    assert "0x00082020: 0x0000 0x0001 0x0002 0x0003" in text


def test_raw_words_zero_does_not_call_memory_read(monkeypatch) -> None:
    calls = install_operations(monkeypatch, make_summary())
    result = metadata_probe.collect_probe_result(
        session(), CPU1_PROFILE, raw_words=0
    )
    assert calls == []
    assert result.raw_metadata is None


def test_operation_failure_preserves_error_identity(monkeypatch) -> None:
    failure = OperationResult(
        False,
        "get_metadata_summary",
        CPU1_PROFILE.name,
        "GET_METADATA_SUMMARY",
        {},
        error=OperationErrorInfo(
            "DSP_STATUS_ERROR",
            "metadata unavailable",
            "GET_METADATA_SUMMARY",
        ),
    )
    monkeypatch.setattr(metadata_probe, "get_metadata_summary", lambda _ctx: failure)
    with pytest.raises(metadata_probe.ProbeOperationError) as caught:
        metadata_probe.collect_probe_result(session(), CPU1_PROFILE)
    assert caught.value.operation == "get_metadata_summary"
    assert caught.value.stage == "GET_METADATA_SUMMARY"
    assert caught.value.code == "DSP_STATUS_ERROR"
    assert caught.value.message == "metadata unavailable"


def test_parser_is_serial_only_and_requires_port() -> None:
    parser = metadata_probe.build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    with pytest.raises(SystemExit):
        parser.parse_args(["--transport", "simulator", "--port", "COM1"])
    args = parser.parse_args(["--port", "COM1"])
    assert not hasattr(args, "transport")


def test_validate_args_rejects_bad_values() -> None:
    parser = metadata_probe.build_arg_parser()
    args = argparse.Namespace(
        port="COM1",
        baud=0,
        raw_words=0,
        timeout_ms=5000,
    )
    with pytest.raises(SystemExit):
        metadata_probe.validate_args(parser, args)


def test_main_returns_failure_for_operation_error(monkeypatch, capsys) -> None:
    def fail(_args):
        raise RuntimeError("operation failed")

    monkeypatch.setattr(metadata_probe, "run", fail)
    assert metadata_probe.main(["--port", "COM1"]) == 1
    assert "operation failed" in capsys.readouterr().out


def test_run_uses_session_discovery_and_disconnects(monkeypatch) -> None:
    created = SimpleNamespace(session=None, transport_config=None)

    class FakeTransport:
        def __init__(self, config) -> None:
            created.transport_config = config

    class FakeSession:
        def __init__(self, config) -> None:
            self.config = config
            self.client = SimpleNamespace(device_info=make_device())
            self.disconnected = False
            created.session = self

        def connect(self):
            return TransportOpenResult(TransportOpenStatus.OPENED, False, "OPEN_COMPLETE")

        def disconnect(self) -> None:
            self.disconnected = True

    discovery_result = operation_result("discover_connected_target")
    monkeypatch.setattr(metadata_probe, "SerialTransport", FakeTransport)
    monkeypatch.setattr(metadata_probe, "UpgradeSession", FakeSession)
    monkeypatch.setattr(
        metadata_probe,
        "discover_connected_target",
        lambda _session: SimpleNamespace(
            result=discovery_result,
            discovered_target=SimpleNamespace(target_profile=CPU1_PROFILE),
        ),
    )
    install_operations(monkeypatch, make_summary())
    args = argparse.Namespace(
        port="COM9",
        baud=19200,
        timeout_ms=7000,
        metadata_address=0x082000,
        raw_words=0,
    )
    result = metadata_probe.run(args)
    assert result.raw_metadata is None
    assert created.session.disconnected
    assert created.transport_config.port == "COM9"
    assert created.transport_config.baudrate == 19200
    assert created.transport_config.tx_timeout_ms == 7000
    assert created.transport_config.rx_timeout_ms == 7000
    assert created.transport_config.autobaud_timeout_ms == 7000
