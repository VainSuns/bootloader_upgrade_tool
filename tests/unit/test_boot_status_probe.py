import json

from bootloader_upgrade_tool.protocol.constants import BootSlot, MetadataRecordType
from bootloader_upgrade_tool.protocol.models import MetadataSummary
from bootloader_upgrade_tool.tools import boot_status_probe


def make_summary(
    *,
    metadata_valid: int = 1,
    latest_record_type: int = MetadataRecordType.IMAGE_VALID,
    boot_attempt_count: int = 0,
    app_confirmed: int = 0,
    entry_point: int = 0x082400,
    image_size_words: int = 1234,
    image_crc32: int = 0x12345678,
    state: int | None = None,
) -> MetadataSummary:
    return MetadataSummary(
        metadata_valid=metadata_valid,
        active_slot=BootSlot.SLOT_A if metadata_valid else BootSlot.AUTO,
        latest_record_type=latest_record_type,
        boot_attempt_count=boot_attempt_count,
        app_confirmed=app_confirmed,
        boot_attempt_limit=3,
        app_version_major=0,
        app_version_minor=0,
        app_version_patch=0,
        app_version_build=0,
        entry_point=entry_point,
        image_crc32=image_crc32,
        state=(1 if metadata_valid else 0) if state is None else state,
        valid_record_count=1 if metadata_valid else 0,
        invalid_record_count=0,
        erased_record_count=15,
        free_record_count=15,
        next_record_index=1 if metadata_valid else 0,
        image_size_words=image_size_words,
        target_device_id=0x377D if metadata_valid else 0,
        target_cpu_id=1 if metadata_valid else 0,
    )


def reason(summary: MetadataSummary) -> str:
    return boot_status_probe.preview_boot_policy(summary).reason


def test_policy_preview_reasons() -> None:
    assert reason(make_summary(metadata_valid=0, state=2)) == "METADATA_INVALID"
    assert (
        reason(
            make_summary(
                metadata_valid=0,
                latest_record_type=0,
                entry_point=0,
                image_size_words=0,
                image_crc32=0,
            )
        )
        == "NO_IMAGE_VALID"
    )
    assert reason(make_summary(image_size_words=0, image_crc32=0, entry_point=0)) == "NO_IMAGE_VALID"
    assert reason(make_summary()) == "SERVICE_NOT_READY"
    assert (
        boot_status_probe.preview_boot_policy(
            make_summary(),
            boot_status_probe.FlashServicePreview("yes", "ATTACHED"),
        ).reason
        == "RUN_FIRST_TRIAL"
    )
    assert reason(make_summary(boot_attempt_count=1)) == "WAIT_APP_CONFIRM"
    preview = boot_status_probe.preview_boot_policy(make_summary(boot_attempt_count=1, app_confirmed=1))
    assert preview.automatic_boot_allowed is True
    assert preview.reason == "APP_CONFIRMED"
    assert reason(make_summary(entry_point=0x082402)) == "BAD_ENTRY"


def test_format_text_contains_pass_and_preview() -> None:
    result = boot_status_probe.BootStatusResult(
        make_summary(boot_attempt_count=1, app_confirmed=1),
        boot_status_probe.BootPolicyPreview(True, "APP_CONFIRMED"),
        boot_status_probe.FlashServicePreview("yes", "ATTACHED"),
    )
    text = boot_status_probe.format_text(result)
    assert "PASS: boot status read" in text
    assert "automatic boot allowed: yes" in text
    assert "reason: APP_CONFIRMED" in text
    assert "reason: ATTACHED" in text


def test_json_formatting() -> None:
    result = boot_status_probe.BootStatusResult(
        make_summary(),
        boot_status_probe.BootPolicyPreview(False, "SERVICE_NOT_READY"),
        boot_status_probe.FlashServicePreview("unknown", "NOT_CHECKED"),
    )
    data = json.loads(boot_status_probe.format_json(result))
    assert data["preview"]["automatic_boot_allowed"] is False
    assert data["preview"]["reason"] == "SERVICE_NOT_READY"


class ReadOnlyClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_metadata_summary(self, *, timeout_ms: int) -> MetadataSummary:
        self.calls.append("get_metadata_summary")
        return make_summary()

    def get_service_status(self, *, timeout_ms: int):
        self.calls.append("get_service_status")
        raise RuntimeError("not available")

    def run(self, *args, **kwargs):  # pragma: no cover
        self.calls.append("run")

    def metadata_append_boot_attempt(self, *args, **kwargs):  # pragma: no cover
        self.calls.append("metadata_append_boot_attempt")

    def metadata_append_app_confirmed(self, *args, **kwargs):  # pragma: no cover
        self.calls.append("metadata_append_app_confirmed")


def test_collect_boot_status_is_read_only() -> None:
    client = ReadOnlyClient()
    result = boot_status_probe.collect_boot_status(client, timeout_ms=123)  # type: ignore[arg-type]
    assert result.preview.reason == "SERVICE_NOT_READY"
    assert client.calls == ["get_metadata_summary", "get_service_status"]
