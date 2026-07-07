from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.protocol.models import MetadataSummary
from bootloader_upgrade_tool.tools.boot_status_probe import BootPolicyPreview, BootStatusResult
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


def status(item: MetadataSummary) -> BootStatusResult:
    return BootStatusResult(item, BootPolicyPreview(False, "TEST"))


def identity() -> dict[str, int]:
    return {
        "entry_point": 0x082400,
        "image_size_words": 32,
        "image_crc32": 0x12345678,
        "app_end": 0x082420,
    }


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


def test_hex2000_is_registered_for_service_loading_commands() -> None:
    parser = cpu1_upgrade.build_arg_parser()

    attach = parser.parse_args(
        [
            "attach-service",
            "--port",
            "COM10",
            "--service-image",
            "service.out",
            "--service-map",
            "service.map",
            "--hex2000",
            "cgroot",
        ]
    )
    confirm = parser.parse_args(
        [
            "confirm",
            "--port",
            "COM10",
            "--service-image",
            "service.out",
            "--service-map",
            "service.map",
            "--hex2000",
            "cgroot",
        ]
    )
    run = parser.parse_args(["run", "--port", "COM10", "--hex2000", "cgroot"])
    flash = parser.parse_args(
        [
            "flash",
            "--port",
            "COM10",
            "--app-image",
            "app.out",
            "--hex2000",
            "cgroot",
        ]
    )
    upgrade = parser.parse_args(
        [
            "upgrade",
            "--port",
            "COM10",
            "--app-image",
            "app.out",
            "--hex2000",
            "cgroot",
        ]
    )

    assert attach.hex2000 == "cgroot"
    assert confirm.hex2000 == "cgroot"
    assert run.hex2000 == "cgroot"
    assert flash.hex2000 == "cgroot"
    assert upgrade.hex2000 == "cgroot"


def test_sector_mask_validation_rejects_sector_a_and_metadata() -> None:
    with pytest.raises(ValueError, match="Sector A"):
        cpu1_upgrade.validate_sector_mask_for_image(0x1, image())
    with pytest.raises(ValueError, match="metadata"):
        cpu1_upgrade.validate_sector_mask_for_image(0x2, image(0x082000, entry=0x082400))
    with pytest.raises(ValueError, match="does not cover"):
        cpu1_upgrade.validate_sector_mask_for_image(0x2, image(0x090000))


def test_resolve_masks_auto_adds_metadata_and_erases_it_first() -> None:
    masks = cpu1_upgrade.resolve_dfu_erase_masks(image(0x090000), None)

    assert masks["requested_mask"] == 0x20
    assert masks["effective_mask"] == 0x22
    assert masks["first_erase_mask"] == 0x2
    assert masks["second_erase_mask"] == 0x20


def test_sector_mask_smaller_than_app_mask_fails() -> None:
    with pytest.raises(ValueError, match="does not cover"):
        cpu1_upgrade.resolve_dfu_erase_masks(image(0x090000), 0x2)


def test_sector_a_mask_fails_before_flash() -> None:
    with pytest.raises(ValueError, match="Sector A"):
        cpu1_upgrade.resolve_dfu_erase_masks(image(), 0x1)


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


def test_flash_same_image_skips_without_attach(monkeypatch) -> None:
    monkeypatch.setattr(cpu1_upgrade, "_load_service", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("attach")))

    result = cpu1_upgrade.run_flash_flow(
        SimpleNamespace(sector_mask=None, force=False),
        object(),  # type: ignore[arg-type]
        image(),
        identity(),
        status(summary(boot_attempt_count=0)),
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "IMAGE_VALID_ALREADY_MATCHES_INPUT"
    assert result["image_valid_written"] is False


def test_flash_same_image_force_executes_flash(monkeypatch) -> None:
    calls: list[tuple] = []

    class Client:
        def metadata_append_image_valid(self, **kwargs):
            calls.append(("image_valid", kwargs))

    class Workflow:
        def __init__(self, client):
            pass

        def erase(self, mask):
            calls.append(("erase", mask))

        def program(self, app):
            calls.append(("program", app))

        def verify(self, app):
            calls.append(("verify", app))

    monkeypatch.setattr(cpu1_upgrade, "_load_service", lambda *args, **kwargs: {"attached": True})
    monkeypatch.setattr(cpu1_upgrade, "UpgradeWorkflow", Workflow)
    monkeypatch.setattr(cpu1_upgrade, "collect_boot_status", lambda *args, **kwargs: status(summary()))

    result = cpu1_upgrade.run_flash_flow(
        SimpleNamespace(sector_mask=None, force=True, timeout_ms=123),
        Client(),  # type: ignore[arg-type]
        image(0x090000),
        identity(),
        status(summary()),
    )

    assert result["action"] == "flashed"
    assert [call[0] for call in calls] == ["erase", "erase", "program", "verify", "image_valid"]
    assert calls[0] == ("erase", 0x2)
    assert calls[1] == ("erase", 0x20)


def test_upgrade_same_confirmed_direct_run_without_attempt_or_attach(monkeypatch) -> None:
    calls: list[tuple] = []

    class Client:
        def transact(self, command, payload, *, timeout_ms):
            calls.append(("run", command, payload, timeout_ms))

    monkeypatch.setattr(cpu1_upgrade, "_load_service", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("attach")))

    result = cpu1_upgrade.run_upgrade_flow(
        SimpleNamespace(sector_mask=None, force=False, timeout_ms=5),
        Client(),  # type: ignore[arg-type]
        image(),
        identity(),
        status(summary(boot_attempt_count=1, app_confirmed=1)),
    )

    assert result["action"] == "skipped"
    assert result["boot_attempt_written"] is False
    assert result["run_sent"] is True
    assert calls[0][0] == "run"


def test_upgrade_attempt_without_confirm_warns_and_does_not_repeat_attempt(monkeypatch) -> None:
    class Client:
        def __init__(self):
            self.calls: list[str] = []

        def transact(self, *args, **kwargs):
            self.calls.append("run")

        def metadata_append_boot_attempt(self, **kwargs):  # pragma: no cover
            self.calls.append("attempt")

    monkeypatch.setattr(cpu1_upgrade, "_load_service", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("attach")))
    client = Client()

    result = cpu1_upgrade.run_upgrade_flow(
        SimpleNamespace(sector_mask=None, force=False, timeout_ms=5),
        client,  # type: ignore[arg-type]
        image(),
        identity(),
        status(summary(boot_attempt_count=1, app_confirmed=0)),
    )

    assert client.calls == ["run"]
    assert result["warning"]["code"] == cpu1_upgrade.WARNING_ATTEMPT_WITHOUT_CONFIRM


def test_upgrade_same_image_without_attempt_attaches_writes_attempt_then_runs(monkeypatch) -> None:
    class Client:
        def __init__(self):
            self.calls: list[tuple] = []

        def metadata_append_boot_attempt(self, **kwargs):
            self.calls.append(("attempt", kwargs))

        def transact(self, *args, **kwargs):
            self.calls.append(("run", args, kwargs))

    monkeypatch.setattr(cpu1_upgrade, "_load_service", lambda *args, **kwargs: {"attached": True})
    client = Client()

    result = cpu1_upgrade.run_upgrade_flow(
        SimpleNamespace(sector_mask=None, force=False, timeout_ms=456),
        client,  # type: ignore[arg-type]
        image(),
        identity(),
        status(summary(boot_attempt_count=0, app_confirmed=0)),
    )

    assert result["boot_attempt_written"] is True
    assert client.calls[0][0] == "attempt"
    assert client.calls[0][1]["entry_point"] == 0x082400
    assert client.calls[0][1]["image_size_words"] == 32
    assert client.calls[0][1]["image_crc32"] == 0x12345678
    assert client.calls[1][0] == "run"


def test_upgrade_no_longer_defaults_to_confirm(monkeypatch) -> None:
    monkeypatch.setattr(cpu1_upgrade, "run_flash_flow", lambda *args, **kwargs: {"post_flash_status": status(summary(boot_attempt_count=0))})
    monkeypatch.setattr(cpu1_upgrade, "ensure_boot_attempt", lambda *args, **kwargs: (True, {"attached": True}))

    class Client:
        def __init__(self):
            self.confirm_called = False

        def transact(self, *args, **kwargs):
            pass

        def metadata_append_app_confirmed(self, **kwargs):  # pragma: no cover
            self.confirm_called = True

    client = Client()
    cpu1_upgrade.run_upgrade_flow(
        SimpleNamespace(sector_mask=None, force=True, timeout_ms=1),
        client,  # type: ignore[arg-type]
        image(),
        identity(),
        status(summary(boot_attempt_count=0)),
    )

    assert client.confirm_called is False


def test_format_text_flash_allows_service_none() -> None:
    text = cpu1_upgrade.format_text(
        "flash",
        {
            "service": None,
            "app": {"entry_point": 0x082400, "generated_sci8_txt": "app.sci8.txt"},
        },
    )

    assert "PASS: cpu1_upgrade flash" in text
    assert "Service descriptor" not in text


def test_format_text_upgrade_allows_service_none() -> None:
    text = cpu1_upgrade.format_text(
        "upgrade",
        {
            "service": None,
            "app": {"entry_point": 0x082400, "generated_sci8_txt": "app.sci8.txt"},
        },
    )

    assert "PASS: cpu1_upgrade upgrade" in text
    assert "Service descriptor" not in text


def test_format_text_upgrade_prints_warning() -> None:
    text = cpu1_upgrade.format_text(
        "upgrade",
        {
            "warning": {
                "code": cpu1_upgrade.WARNING_ATTEMPT_WITHOUT_CONFIRM,
                "message": "needs attention",
            },
        },
    )

    assert "WARNING[BOOT_ATTEMPT_WITHOUT_APP_CONFIRMED]" in text
    assert "needs attention" in text
