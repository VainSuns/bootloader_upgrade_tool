from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.protocol.models import MetadataSummary
from bootloader_upgrade_tool.tools import cpu1_upgrade


def image(address: int = 0x082400, *, entry: int = 0x082400) -> FirmwareImage:
    return FirmwareImage(
        source_out_file="app.out",
        generated_hex_file="app.sci8.txt",
        entry_point=entry,
        blocks=(FirmwareBlock(address, tuple(range(16))),),
        file_checksum="fixture",
        format_info={},
    )


def summary(*, metadata_valid: int = 1, boot_attempt_count: int = 1, app_confirmed: int = 0) -> MetadataSummary:
    return MetadataSummary(
        metadata_valid=metadata_valid,
        active_slot=1,
        latest_record_type=2,
        boot_attempt_count=boot_attempt_count,
        app_confirmed=app_confirmed,
        boot_attempt_limit=3,
        app_version_major=0,
        app_version_minor=0,
        app_version_patch=0,
        app_version_build=0,
        entry_point=0x082400,
        image_crc32=0x12345678,
        state=1 if metadata_valid else 0,
        valid_record_count=2,
        invalid_record_count=0,
        erased_record_count=14,
        free_record_count=14,
        next_record_index=2,
        image_size_words=32,
        target_device_id=0x377D,
        target_cpu_id=1,
    )


def test_arg_defaults_and_aliases() -> None:
    args = cpu1_upgrade.build_arg_parser().parse_args(
        ["status", "--port", "COM10", "--json"]
    )
    cpu1_upgrade.normalize_output(args)

    assert args.baud == 9600
    assert args.autobaud_mode == "always"
    assert args.output == "json"


def test_help_describes_subcommands_and_options() -> None:
    parser = cpu1_upgrade.build_arg_parser()
    text = parser.format_help()

    assert "read metadata summary" in text
    assert "SERVICE_ATTACH" in text
    assert "examples:" in text


def test_invalid_autobaud_mode_rejected() -> None:
    with pytest.raises(SystemExit):
        cpu1_upgrade.build_arg_parser().parse_args(
            ["status", "--port", "COM10", "--autobaud-mode", "auto"]
        )


def test_hex_aliases_map_to_sci8_names() -> None:
    args = cpu1_upgrade.build_arg_parser().parse_args(
        [
            "flash",
            "--port",
            "COM10",
            "--service-image",
            "service.out",
            "--service-map",
            "service.map",
            "--app-image",
            "app.out",
            "--hex-file",
            "app.sci8.txt",
            "--keep-hex",
            "--sector-mask",
            "0x2",
        ]
    )

    assert args.sci8_txt == "app.sci8.txt"
    assert args.keep_sci8_txt is True
    assert args.sector_mask == 0x2


def test_sector_mask_validation_rejects_sector_a_and_metadata() -> None:
    with pytest.raises(ValueError, match="Sector A"):
        cpu1_upgrade.validate_sector_mask_for_image(0x1, image())
    with pytest.raises(ValueError, match="metadata"):
        cpu1_upgrade.validate_sector_mask_for_image(0x2, image(0x082000, entry=0x082400))
    with pytest.raises(ValueError, match="does not cover"):
        cpu1_upgrade.validate_sector_mask_for_image(0x2, image(0x090000))


def test_confirm_requires_current_boot_attempt() -> None:
    class Client:
        def get_metadata_summary(self, *, timeout_ms):
            return summary(boot_attempt_count=0)

    with pytest.raises(cpu1_upgrade.CliToolError) as captured:
        cpu1_upgrade._confirm_metadata(Client(), 123)  # type: ignore[arg-type]

    assert captured.value.error_code == "BOOT_ATTEMPT_REQUIRED"


def test_confirm_writes_current_summary_and_does_not_run(monkeypatch) -> None:
    calls: list[tuple] = []

    class Client:
        def __init__(self) -> None:
            self.count = 0

        def get_metadata_summary(self, *, timeout_ms):
            calls.append(("summary", timeout_ms))
            self.count += 1
            return summary(app_confirmed=1 if self.count > 1 else 0)

        def metadata_append_app_confirmed(self, **kwargs):
            calls.append(("confirm", kwargs))

        def run(self):  # pragma: no cover
            calls.append(("run",))

    result = cpu1_upgrade._confirm_metadata(Client(), 456)  # type: ignore[arg-type]

    assert result.preview.reason == "APP_CONFIRMED"
    assert calls[1][0] == "confirm"
    assert calls[1][1]["entry_point"] == 0x082400
    assert calls[1][1]["image_size_words"] == 32
    assert calls[1][1]["image_crc32"] == 0x12345678
    assert "run" not in [call[0] for call in calls]


def test_upgrade_no_run_stops_after_flash(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cpu1_upgrade, "run_cpu1_flash", lambda args: calls.append("flash") or {"flash": True})
    monkeypatch.setattr(cpu1_upgrade, "run_cpu1_run", lambda args: calls.append("run"))
    monkeypatch.setattr(cpu1_upgrade, "run_cpu1_confirm", lambda args: calls.append("confirm"))

    result = cpu1_upgrade.run_cpu1_upgrade(SimpleNamespace(dry_run=False, no_run=True, no_confirm=False))

    assert calls == ["flash"]
    assert result["run_sent"] is False


def test_upgrade_no_confirm_runs_but_skips_confirm(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cpu1_upgrade, "run_cpu1_flash", lambda args: calls.append("flash") or {})
    monkeypatch.setattr(cpu1_upgrade, "run_cpu1_run", lambda args: calls.append("run") or {})
    monkeypatch.setattr(cpu1_upgrade, "run_cpu1_confirm", lambda args: calls.append("confirm"))

    result = cpu1_upgrade.run_cpu1_upgrade(SimpleNamespace(dry_run=False, no_run=False, no_confirm=True))

    assert calls == ["flash", "run"]
    assert result["app_confirmed"] is False


def test_upgrade_runs_before_confirm(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cpu1_upgrade, "run_cpu1_flash", lambda args: calls.append("flash") or {})
    monkeypatch.setattr(cpu1_upgrade, "run_cpu1_run", lambda args: calls.append("run") or {})
    monkeypatch.setattr(cpu1_upgrade, "run_cpu1_confirm", lambda args: calls.append("confirm") or {})

    result = cpu1_upgrade.run_cpu1_upgrade(SimpleNamespace(dry_run=False, no_run=False, no_confirm=False))

    assert calls == ["flash", "run", "confirm"]
    assert result["app_confirmed"] is True
