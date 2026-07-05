from types import SimpleNamespace

from bootloader_upgrade_tool.firmware import FirmwareBlock, FirmwareImage
from bootloader_upgrade_tool.firmware.ti_map import TiMapSymbols
from bootloader_upgrade_tool.protocol.models import DeviceInfo
from bootloader_upgrade_tool.tools import service_flash_probe


def _image(path: str, address: int) -> FirmwareImage:
    return FirmwareImage(
        source_out_file=path,
        generated_hex_file=path,
        entry_point=address,
        blocks=(FirmwareBlock(address, tuple(range(16))),),
        file_checksum="fixture",
        format_info={"format": "fixture"},
    )


def test_arg_parser_defaults() -> None:
    args = service_flash_probe.build_arg_parser().parse_args(
        [
            "--transport",
            "simulator",
            "--service-image",
            "service.out",
            "--service-map",
            "service.map",
            "--app-image",
            "app.out",
        ]
    )
    assert args.sector_mask == 0x00003FFE
    assert args.run is False
    assert args.service_image == "service.out"
    assert args.service_map == "service.map"
    assert args.app_image == "app.out"


def test_arg_parser_run_flag() -> None:
    args = service_flash_probe.build_arg_parser().parse_args(
        [
            "--transport",
            "simulator",
            "--service-image",
            "service.out",
            "--service-map",
            "service.map",
            "--app-image",
            "app.out",
            "--run",
        ]
    )
    assert args.run is True


def test_run_attaches_then_dfu_then_optional_run(monkeypatch) -> None:
    calls: list[tuple] = []
    service = _image("service.out", 0x010000)
    app = _image("app.out", 0x082400)
    symbols = TiMapSymbols(descriptor_address=0x013000, crc_patch_address=0x013014, api_table_address=0x013020)

    def fake_load_image(path, hex2000):
        return (service if str(path) == "service.out" else app), None

    class FakeClient:
        device_info = DeviceInfo(0x377D, 1, 0, 1, 0, 1, 0, 256, 248, 1, 1, 3, 0x30522F)

        def __init__(self, device, default_timeout_ms, clear_input_before_request):
            calls.append(("client", default_timeout_ms, clear_input_before_request))

        def open(self, wait_slave_timeout_ms, device_info_timeout_ms):
            calls.append(("open", wait_slave_timeout_ms, device_info_timeout_ms))

        def close(self):
            calls.append(("close",))

    class FakeWorkflow:
        def __init__(self, client):
            calls.append(("workflow",))

        def load_and_attach_service(self, image, descriptor_address):
            calls.append(("attach", image, descriptor_address))
            return SimpleNamespace(
                service_state=1,
                service_major=2,
                service_minor=4,
                capabilities=0xF,
                loaded_image_crc32=0x12345678,
            )

        def dfu(self, sector_mask, image):
            calls.append(("dfu", sector_mask, image))

        def run(self, image):
            calls.append(("run", image))

    monkeypatch.setattr(service_flash_probe, "_load_image", fake_load_image)
    monkeypatch.setattr(service_flash_probe, "parse_flash_service_symbols_from_map", lambda path: symbols)
    def fake_patch(image, **kwargs):
        calls.append(("patch", kwargs))
        return image

    monkeypatch.setattr(service_flash_probe, "patch_flash_service_image", fake_patch)
    monkeypatch.setattr(service_flash_probe, "ProtocolClient", FakeClient)
    monkeypatch.setattr(service_flash_probe, "UpgradeWorkflow", FakeWorkflow)
    monkeypatch.setattr(service_flash_probe, "_device", lambda args: object())

    args = service_flash_probe.build_arg_parser().parse_args(
        [
            "--transport",
            "simulator",
            "--service-image",
            "service.out",
            "--service-map",
            "service.map",
            "--app-image",
            "app.out",
            "--sector-mask",
            "0x2",
            "--run",
        ]
    )
    result = service_flash_probe.run(args)

    assert [call[0] for call in calls] == ["client", "workflow", "open", "patch", "attach", "dfu", "run", "close"]
    assert calls[3][1]["load_order"] == "descriptor_last"
    assert calls[3][1]["max_data_words"] == 248
    assert calls[4] == ("attach", service, 0x013000)
    assert calls[5] == ("dfu", 0x2, app)
    assert calls[6] == ("run", app)
    assert result.sector_mask == 0x2
    assert result.run is True
    assert result.service_crc32 == 0x12345678
