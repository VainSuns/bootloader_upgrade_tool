import json
import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from bootloader_upgrade_tool.app_resources import (
    AppResourceConfigurationError,
    AppResourceNotFoundError,
    AppResourceProvider,
    DevelopmentResourceProvider,
    FlashServiceResources,
    InstalledResourceProvider,
    default_development_resource_config_path,
    load_development_resource_provider,
)


def _config(path: Path, image: Path, map_file: Path, **extra) -> None:
    path.write_text(json.dumps({
        "flash_service_image_path": str(image),
        "flash_service_map_path": str(map_file),
        **extra,
    }), encoding="utf-8")


def test_development_provider_loads_exact_absolute_resource_pair(tmp_path) -> None:
    image, map_file = tmp_path / "service.out", tmp_path / "service.map"
    image.write_bytes(b"out")
    map_file.write_text("map", encoding="utf-8")
    config = tmp_path / "resources.json"
    _config(config, image, map_file)

    provider = load_development_resource_provider(config)

    assert isinstance(provider, AppResourceProvider)
    assert provider.flash_service_image_path() == image.resolve()
    assert provider.flash_service_map_path() == map_file.resolve()
    with pytest.raises(FrozenInstanceError):
        provider.resources = provider.resources


@pytest.mark.parametrize(
    "payload",
    (
        [],
        {},
        {"flash_service_image_path": "x"},
        {"flash_service_image_path": 1, "flash_service_map_path": "x.map"},
        {"flash_service_image_path": "x.out", "flash_service_map_path": "x.map"},
        {"flash_service_image_path": "D:/x.bin", "flash_service_map_path": "D:/x.map"},
        {"flash_service_image_path": "D:/x.out", "flash_service_map_path": "D:/x.txt"},
        {"flash_service_image_path": "D:/x.out", "flash_service_map_path": "D:/x.map", "extra": "x"},
    ),
)
def test_development_provider_rejects_wrong_shape_values_and_paths(tmp_path, payload) -> None:
    config = tmp_path / "resources.json"
    config.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AppResourceConfigurationError, match=re.escape(str(config))):
        DevelopmentResourceProvider.from_config(config)


def test_development_provider_reports_missing_and_malformed_config(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(AppResourceConfigurationError, match="Copy.*example"):
        load_development_resource_provider(missing)
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(AppResourceConfigurationError, match=re.escape(str(malformed))):
        DevelopmentResourceProvider.from_config(malformed)


def test_provider_validates_each_resource_at_access_time(tmp_path) -> None:
    image, map_file = tmp_path / "service.txt", tmp_path / "service.map"
    config = tmp_path / "resources.json"
    _config(config, image, map_file)
    provider = DevelopmentResourceProvider.from_config(config)
    with pytest.raises(AppResourceNotFoundError, match=re.escape(str(image))):
        provider.flash_service_image_path()
    image.write_text("sci8", encoding="utf-8")
    with pytest.raises(AppResourceNotFoundError, match=re.escape(str(map_file))):
        provider.flash_service_map_path()


def test_resource_pair_is_normalized_distinct_and_path_only(tmp_path) -> None:
    resources = FlashServiceResources(tmp_path / "a.out", tmp_path / "a.map")
    assert resources.image_path.is_absolute() and resources.map_path.is_absolute()
    with pytest.raises(AppResourceConfigurationError, match="must differ"):
        FlashServiceResources(tmp_path / "same.out", tmp_path / "same.out")
    with pytest.raises(TypeError, match="Path values"):
        FlashServiceResources("a.out", Path("a.map"))  # type: ignore[arg-type]


def test_installed_provider_does_not_choose_a_layout() -> None:
    provider = InstalledResourceProvider()
    for method in (provider.flash_service_image_path, provider.flash_service_map_path):
        with pytest.raises(AppResourceConfigurationError, match="packaging stage"):
            method()


def test_default_development_config_path_is_explicit_pc_config_location() -> None:
    path = default_development_resource_config_path()
    assert path.parts[-3:] == ("pc", "config", "development_app_resources.json")
