from types import SimpleNamespace

import pytest

from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.firmware.ti_map import TiMapSymbols
from bootloader_upgrade_tool.protocol.models import DeviceInfo, MetadataSummary
from bootloader_upgrade_tool.tools import app_confirm_probe


def _service_image() -> FirmwareImage:
    return FirmwareImage(
        source_out_file="service.out",
        generated_hex_file="service.txt",
        entry_point=0x013000,
        blocks=(FirmwareBlock(0x013000, tuple(range(32))),),
        file_checksum="fixture",
        format_info={},
    )


def _summary(*, boot_attempt_count: int = 1, app_confirmed: int = 0) -> MetadataSummary:
    return MetadataSummary(
        metadata_valid=1,
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
        state=1,
        valid_record_count=2,
        invalid_record_count=0,
        erased_record_count=14,
        free_record_count=14,
        next_record_index=2,
        image_size_words=3909,
        target_device_id=0x377D,
        target_cpu_id=1,
    )


def test_run_writes_app_confirmed_without_run(monkeypatch) -> None:
    calls: list[tuple] = []
    symbols = TiMapSymbols(descriptor_address=0x013000, crc_patch_address=0x013014, api_table_address=0x013020)

    class FakeClient:
        device_info = DeviceInfo(0x377D, 1, 0, 1, 0, 1, 0, 256, 248, 1, 1, 3, 0)

        def __init__(self, device, default_timeout_ms, clear_input_before_request):
            calls.append(("client", default_timeout_ms, clear_input_before_request))
            self.summary_calls = 0

        def open(self, wait_slave_timeout_ms, device_info_timeout_ms):
            calls.append(("open", wait_slave_timeout_ms, device_info_timeout_ms))

        def close(self):
            calls.append(("close",))

        def get_metadata_summary(self, *, timeout_ms):
            calls.append(("summary", timeout_ms))
            self.summary_calls += 1
            return _summary(app_confirmed=1 if self.summary_calls > 1 else 0)

        def metadata_append_app_confirmed(self, **kwargs):
            calls.append(("confirm", kwargs))

        def run(self, *args, **kwargs):  # pragma: no cover
            calls.append(("run",))

    class FakeWorkflow:
        def __init__(self, client):
            calls.append(("workflow",))

        def load_and_attach_service(self, image, descriptor_address):
            calls.append(("attach", image, descriptor_address))
            return SimpleNamespace(service_state=2)

    monkeypatch.setattr(app_confirm_probe, "_load_image", lambda path, hex2000: (_service_image(), None))
    monkeypatch.setattr(app_confirm_probe, "parse_flash_service_symbols_from_map", lambda path: symbols)
    monkeypatch.setattr(app_confirm_probe, "patch_flash_service_image", lambda image, **kwargs: image)
    monkeypatch.setattr(app_confirm_probe, "ProtocolClient", FakeClient)
    monkeypatch.setattr(app_confirm_probe, "UpgradeWorkflow", FakeWorkflow)
    monkeypatch.setattr(app_confirm_probe, "_device", lambda args: object())

    args = app_confirm_probe.build_arg_parser().parse_args(
        [
            "--transport",
            "simulator",
            "--service-image",
            "service.out",
            "--service-map",
            "service.map",
            "--autobaud-mode",
            "always",
        ]
    )
    assert args.autobaud_mode == "always"
    result = app_confirm_probe.run(args)

    assert result.metadata.app_confirmed == 1
    assert "run" not in [call[0] for call in calls]
    assert [call[0] for call in calls] == [
        "client", "workflow", "open", "attach", "summary", "confirm", "summary", "close"
    ]


def test_run_requires_boot_attempt(monkeypatch) -> None:
    class FakeClient:
        device_info = DeviceInfo(0x377D, 1, 0, 1, 0, 1, 0, 256, 248, 1, 1, 3, 0)

        def __init__(self, *args, **kwargs):
            pass

        def open(self, **kwargs):
            pass

        def close(self):
            pass

        def get_metadata_summary(self, *, timeout_ms):
            return _summary(boot_attempt_count=0)

    class FakeWorkflow:
        def __init__(self, client):
            pass

        def load_and_attach_service(self, image, descriptor_address):
            return SimpleNamespace(service_state=2)

    symbols = TiMapSymbols(descriptor_address=0x013000, crc_patch_address=0x013014, api_table_address=0x013020)
    monkeypatch.setattr(app_confirm_probe, "_load_image", lambda path, hex2000: (_service_image(), None))
    monkeypatch.setattr(app_confirm_probe, "parse_flash_service_symbols_from_map", lambda path: symbols)
    monkeypatch.setattr(app_confirm_probe, "patch_flash_service_image", lambda image, **kwargs: image)
    monkeypatch.setattr(app_confirm_probe, "ProtocolClient", FakeClient)
    monkeypatch.setattr(app_confirm_probe, "UpgradeWorkflow", FakeWorkflow)
    monkeypatch.setattr(app_confirm_probe, "_device", lambda args: object())

    args = app_confirm_probe.build_arg_parser().parse_args(
        ["--transport", "simulator", "--service-image", "service.out", "--service-map", "service.map"]
    )
    with pytest.raises(RuntimeError, match="BOOT_ATTEMPT"):
        app_confirm_probe.run(args)
