import json
import re
import subprocess
from pathlib import Path

import pytest

from bootloader_upgrade_tool.gui import global_settings
from bootloader_upgrade_tool.gui.global_settings import (
    ConnectionTimeoutSettings,
    FlashLibSettings,
    GuiGlobalSettings,
    Hex2000Settings,
    TemporaryFileSettings,
    load_global_settings,
    validate_global_settings,
)


def write_config(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def issue_fields(settings: GuiGlobalSettings) -> set[str]:
    return {issue.field for issue in validate_global_settings(settings)}


def test_loads_example_config() -> None:
    settings = load_global_settings(Path("pc/config/gui_global_settings.example.json"))

    assert settings.flash_lib.descriptor_symbol == "g_boot_flash_service_descriptor"
    assert settings.connection_timeouts.tx_timeout_ms == 1000
    assert settings.connection_timeouts.rx_timeout_ms == 1000
    assert settings.connection_timeouts.autobaud_timeout_ms == 5000
    assert settings.temporary_files.keep_generated_sci8_txt is False


def test_loads_explicit_temporary_config(tmp_path) -> None:
    config = write_config(
        tmp_path / "settings.json",
        {
            "hex2000": {"executable_path": "C:/ti/bin/hex2000.exe"},
            "flash_lib": {
                "service_image_path": "build/service.out",
                "service_map_path": "build/service.map",
                "descriptor_symbol": "custom_descriptor",
            },
            "temporary_files": {
                "sci8_temp_dir": str(tmp_path / "sci8"),
                "keep_generated_sci8_txt": True,
            },
            "connection_timeouts": {
                "tx_timeout_ms": 11,
                "rx_timeout_ms": 22,
                "autobaud_timeout_ms": 33,
            },
        },
    )

    settings = load_global_settings(config)

    assert settings.source_path == config
    assert settings.hex2000.executable_path == "C:/ti/bin/hex2000.exe"
    assert settings.flash_lib.service_image_path == "build/service.out"
    assert settings.flash_lib.service_map_path == "build/service.map"
    assert settings.flash_lib.descriptor_symbol == "custom_descriptor"
    assert settings.temporary_files.resolved_sci8_temp_dir == tmp_path / "sci8"
    assert settings.temporary_files.keep_generated_sci8_txt is True
    assert settings.connection_timeouts == ConnectionTimeoutSettings(11, 22, 33)


def test_falls_back_when_user_config_is_missing(monkeypatch, tmp_path) -> None:
    user_config = tmp_path / "missing.json"
    example_config = write_config(
        tmp_path / "example.json",
        {"flash_lib": {"descriptor_symbol": "fallback_descriptor"}},
    )
    monkeypatch.setattr(global_settings, "USER_CONFIG_PATH", user_config)
    monkeypatch.setattr(global_settings, "EXAMPLE_CONFIG_PATH", example_config)

    settings = load_global_settings()

    assert settings.source_path == example_config
    assert settings.flash_lib.descriptor_symbol == "fallback_descriptor"


def test_uses_built_in_defaults_when_no_config_exists(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(global_settings, "USER_CONFIG_PATH", tmp_path / "missing-user.json")
    monkeypatch.setattr(global_settings, "EXAMPLE_CONFIG_PATH", tmp_path / "missing-example.json")

    settings = load_global_settings()

    assert settings.source_path is None
    assert settings.hex2000 == Hex2000Settings()
    assert settings.flash_lib == FlashLibSettings()
    assert settings.temporary_files == TemporaryFileSettings()
    assert settings.connection_timeouts == ConnectionTimeoutSettings()


def test_fills_defaults_for_missing_sections_and_fields(tmp_path) -> None:
    config = write_config(
        tmp_path / "settings.json",
        {
            "hex2000": {"executable_path": "hex2000.exe"},
            "connection_timeouts": {"rx_timeout_ms": 2000},
        },
    )

    settings = load_global_settings(config)

    assert settings.hex2000.executable_path == "hex2000.exe"
    assert settings.flash_lib.service_image_path == ""
    assert settings.flash_lib.service_map_path == ""
    assert settings.flash_lib.descriptor_symbol == "g_boot_flash_service_descriptor"
    assert settings.connection_timeouts.tx_timeout_ms == 1000
    assert settings.connection_timeouts.rx_timeout_ms == 2000
    assert settings.connection_timeouts.autobaud_timeout_ms == 5000


def test_timeout_string_number_is_accepted_from_config(tmp_path) -> None:
    config = write_config(
        tmp_path / "settings.json",
        {"connection_timeouts": {"tx_timeout_ms": "2500"}},
    )

    settings = load_global_settings(config)

    assert settings.connection_timeouts.tx_timeout_ms == 2500
    assert "connection_timeouts.tx_timeout_ms" not in issue_fields(settings)


def test_timeout_string_text_reports_validation_issue(tmp_path) -> None:
    config = write_config(
        tmp_path / "settings.json",
        {"connection_timeouts": {"tx_timeout_ms": "abc"}},
    )

    settings = load_global_settings(config)

    assert settings.connection_timeouts.tx_timeout_ms == "abc"
    assert "connection_timeouts.tx_timeout_ms" in issue_fields(settings)


def test_timeout_boolean_reports_validation_issue(tmp_path) -> None:
    config = write_config(
        tmp_path / "settings.json",
        {"connection_timeouts": {"rx_timeout_ms": False}},
    )

    settings = load_global_settings(config)

    assert settings.connection_timeouts.rx_timeout_ms is False
    assert "connection_timeouts.rx_timeout_ms" in issue_fields(settings)


def test_timeout_null_uses_default(tmp_path) -> None:
    config = write_config(
        tmp_path / "settings.json",
        {"connection_timeouts": {"autobaud_timeout_ms": None}},
    )

    settings = load_global_settings(config)

    assert settings.connection_timeouts.autobaud_timeout_ms == 5000
    assert "connection_timeouts.autobaud_timeout_ms" not in issue_fields(settings)


def test_validates_empty_path_fields_without_crashing() -> None:
    settings = GuiGlobalSettings()

    assert issue_fields(settings) == {
        "hex2000.executable_path",
        "flash_lib.service_image_path",
        "flash_lib.service_map_path",
    }
    assert settings.temporary_files.resolved_sci8_temp_dir.is_absolute()


@pytest.mark.parametrize(
    ("field", "timeouts"),
    [
        ("connection_timeouts.tx_timeout_ms", ConnectionTimeoutSettings(0, 1, 1)),
        ("connection_timeouts.rx_timeout_ms", ConnectionTimeoutSettings(1, -1, 1)),
        ("connection_timeouts.autobaud_timeout_ms", ConnectionTimeoutSettings(1, 1, 0)),
    ],
)
def test_validates_invalid_timeout_values(field: str, timeouts: ConnectionTimeoutSettings) -> None:
    settings = GuiGlobalSettings(
        hex2000=Hex2000Settings("hex2000.exe"),
        flash_lib=FlashLibSettings("service.out", "service.map", "descriptor"),
        connection_timeouts=timeouts,
    )

    assert field in issue_fields(settings)


def test_descriptor_symbol_is_configurable_and_not_address_based(tmp_path) -> None:
    config = write_config(
        tmp_path / "settings.json",
        {"flash_lib": {"descriptor_symbol": "my_descriptor"}},
    )

    settings = load_global_settings(config)

    assert settings.flash_lib.descriptor_symbol == "my_descriptor"
    assert "flash_lib.descriptor_symbol" not in issue_fields(settings)


def test_new_module_does_not_hardcode_descriptor_address() -> None:
    source = Path(global_settings.__file__).read_text(encoding="utf-8")

    assert "descriptor_address" not in source
    assert not re.search(r"0x[0-9A-Fa-f]{4,}", source)


def test_loader_does_not_open_ports_or_connect_or_call_operations_or_subprocess(
    monkeypatch,
    tmp_path,
) -> None:
    config = write_config(tmp_path / "settings.json", {})
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("subprocess.run called"))

    settings = load_global_settings(config)

    assert settings.source_path == config
    source = Path(global_settings.__file__).read_text(encoding="utf-8")
    forbidden = (
        "SerialTransport",
        "SerialTransport.open",
        "UpgradeSession",
        "UpgradeSession.connect",
        "operations",
        "subprocess",
        "hex2000 ",
        "parse_out",
        "parse_map",
    )
    assert all(item not in source for item in forbidden)
