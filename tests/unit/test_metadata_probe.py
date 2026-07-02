import argparse
import json

import pytest

from bootloader_upgrade_tool.protocol.constants import BootSlot, MetadataRecordType
from bootloader_upgrade_tool.protocol.models import DeviceInfo, MetadataSummary
from bootloader_upgrade_tool.tools import metadata_probe


def make_device() -> DeviceInfo:
    return DeviceInfo(
        device_id=0x377D,
        cpu_id=1,
        kernel_ver_major=0,
        kernel_ver_minor=1,
        kernel_ver_patch=0,
        protocol_ver=1,
        feature_flags=0x008F,
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


class FakeClient:
    def __init__(self, summary: MetadataSummary) -> None:
        self.summary = summary
        self.raw_reads: list[tuple[int, int, int]] = []
        self.ping_called = False

    def ping(self, *, timeout_ms: int) -> None:
        self.ping_called = True

    def get_device_info(self, *, timeout_ms: int) -> DeviceInfo:
        return make_device()

    def get_metadata_summary(self, *, timeout_ms: int) -> MetadataSummary:
        return self.summary

    def flash_read_metadata(
        self, address: int, word_count: int, *, timeout_ms: int
    ) -> tuple[int, ...]:
        self.raw_reads.append((address, word_count, timeout_ms))
        return tuple(range(word_count))


def test_json_formatting_for_blank_metadata_summary() -> None:
    result = metadata_probe.collect_probe_result(
        FakeClient(make_summary()),  # type: ignore[arg-type]
    )

    data = json.loads(metadata_probe.format_json(result))

    assert data["device"]["target_device_id"] == 0x377D
    assert data["metadata_summary"]["metadata_valid"] is False
    assert data["metadata_summary"]["latest_record_type"] == "NONE"
    assert data["raw_metadata"] is None


def test_json_formatting_for_valid_image_summary() -> None:
    result = metadata_probe.collect_probe_result(
        FakeClient(
            make_summary(
                latest_record_type=MetadataRecordType.IMAGE_VALID,
                entry_point=0x082400,
            )
        ),  # type: ignore[arg-type]
    )

    data = json.loads(metadata_probe.format_json(result))

    assert data["metadata_summary"]["metadata_valid"] is True
    assert data["metadata_summary"]["latest_record_type"] == "IMAGE_VALID"
    assert data["metadata_summary"]["entry_point"] == 0x082400
    assert data["metadata_summary"]["app_version"] == "1.2.3.4"
    assert data["metadata_summary"]["target_device_id"] == 0x377D
    assert data["metadata_summary"]["target_cpu_id"] == 1


def test_json_formatting_for_boot_attempt_summary() -> None:
    result = metadata_probe.collect_probe_result(
        FakeClient(
            make_summary(
                latest_record_type=MetadataRecordType.BOOT_ATTEMPT,
                boot_attempt_count=1,
                entry_point=0x082400,
            )
        ),  # type: ignore[arg-type]
    )

    data = json.loads(metadata_probe.format_json(result))

    assert data["metadata_summary"]["latest_record_type"] == "BOOT_ATTEMPT"
    assert data["metadata_summary"]["boot_attempt_count"] == 1
    assert data["metadata_summary"]["app_confirmed"] is False


def test_text_formatting_contains_key_fields() -> None:
    result = metadata_probe.collect_probe_result(
        FakeClient(
            make_summary(
                latest_record_type=MetadataRecordType.BOOT_ATTEMPT,
                boot_attempt_count=1,
                entry_point=0x082400,
            )
        ),  # type: ignore[arg-type]
        raw_words=4,
    )

    text = metadata_probe.format_text(result)

    assert "target_device_id: 0x377D" in text
    assert "latest_record_type: BOOT_ATTEMPT" in text
    assert "entry_point: 0x00082400" in text
    assert "Raw Metadata:" in text
    assert "0x00082000: 0x0000 0x0001 0x0002 0x0003" in text


def test_serial_transport_without_port_fails() -> None:
    parser = metadata_probe.build_arg_parser()
    args = parser.parse_args(["--transport", "serial"])

    with pytest.raises(SystemExit):
        metadata_probe.validate_args(parser, args)


def test_raw_words_zero_does_not_call_flash_read_metadata() -> None:
    client = FakeClient(make_summary())

    result = metadata_probe.collect_probe_result(  # type: ignore[arg-type]
        client,
        raw_words=0,
    )

    assert client.ping_called is True
    assert client.raw_reads == []
    assert result.raw_metadata is None


def test_raw_words_includes_raw_metadata_words() -> None:
    client = FakeClient(make_summary())

    result = metadata_probe.collect_probe_result(  # type: ignore[arg-type]
        client,
        metadata_address=0x082020,
        raw_words=3,
        timeout_ms=7000,
    )

    assert client.raw_reads == [(0x082020, 3, 7000)]
    assert result.raw_metadata == {"address": 0x082020, "words": [0, 1, 2]}


def test_negative_raw_words_rejected() -> None:
    with pytest.raises(ValueError, match="raw_words"):
        metadata_probe.collect_probe_result(  # type: ignore[arg-type]
            FakeClient(make_summary()),
            raw_words=-1,
        )


def test_validate_args_rejects_bad_values() -> None:
    parser = metadata_probe.build_arg_parser()
    args = argparse.Namespace(
        transport="simulator",
        port=None,
        baud=0,
        raw_words=0,
        timeout_ms=5000,
    )

    with pytest.raises(SystemExit):
        metadata_probe.validate_args(parser, args)
