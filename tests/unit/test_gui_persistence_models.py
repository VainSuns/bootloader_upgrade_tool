from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bootloader_upgrade_tool.gui.persistence_models import (
    GlobalCommandSettings,
    GlobalSettingsDocument,
    MAX_RECENT_SESSIONS,
    RecentSessionEntry,
    RuntimeCacheDocument,
    SessionDocument,
    TargetSessionSettings,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import EraseScope, RuntimeCpuId


UTC = timezone.utc


def test_default_session_is_valid_and_domain_isolated():
    document = SessionDocument()
    assert document.selected_transport == "sci_rs232"
    assert dict(document.transport_configs["sci_rs232"]) == {}
    assert set(document.target_settings) == set(RuntimeCpuId)
    assert all(document.target_settings[cpu].cpu_id is cpu for cpu in RuntimeCpuId)
    assert {field.name for field in fields(GlobalSettingsDocument)} == {
        "schema_version", "hex2000_executable_path", "command", "log_output_path"
    }


def test_session_rejects_invalid_targets_and_transport():
    with pytest.raises(ValueError, match="exactly"):
        SessionDocument(target_settings={RuntimeCpuId.CPU1: TargetSessionSettings(RuntimeCpuId.CPU1)})
    with pytest.raises(ValueError, match="does not match"):
        SessionDocument(target_settings={
            RuntimeCpuId.CPU1: TargetSessionSettings(RuntimeCpuId.CPU2),
            RuntimeCpuId.CPU2: TargetSessionSettings(RuntimeCpuId.CPU2),
        })
    with pytest.raises(ValueError, match="selected_transport"):
        SessionDocument(selected_transport="tcp", transport_configs={"sci_rs232": {}})


@pytest.mark.parametrize("field,value", [("sector_mask", -1), ("sector_mask", True), ("custom_sector_mask", -1)])
def test_target_masks_reject_negative_and_bool(field, value):
    with pytest.raises(ValueError):
        TargetSessionSettings(RuntimeCpuId.CPU1, **{field: value})


def test_target_rejects_invalid_erase_scope():
    with pytest.raises(TypeError):
        TargetSessionSettings(RuntimeCpuId.CPU1, erase_scope="custom")


def test_transport_configuration_is_deeply_immutable_and_strict():
    source = {"sci_rs232": {"endpoint": {"ports": ["COM1"]}}}
    document = SessionDocument(transport_configs=source)
    source["sci_rs232"]["endpoint"]["ports"].append("COM2")
    assert document.transport_configs["sci_rs232"]["endpoint"]["ports"] == ("COM1",)
    with pytest.raises(TypeError):
        document.transport_configs["sci_rs232"]["endpoint"]["x"] = 1
    with pytest.raises(TypeError, match="keys"):
        SessionDocument(transport_configs={"sci_rs232": {1: "bad"}})
    with pytest.raises(TypeError, match="unsupported"):
        SessionDocument(transport_configs={"sci_rs232": {"bad": object()}})
    with pytest.raises(TypeError, match="float"):
        SessionDocument(transport_configs={"sci_rs232": {"bad": float("nan")}})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_ms": 0}, {"timeout_ms": True}, {"max_retries": -1},
        {"max_retries": False}, {"retry_backoff_ms": -1},
    ],
)
def test_global_command_integer_validation(kwargs):
    with pytest.raises(ValueError):
        GlobalCommandSettings(**kwargs)


def test_recent_entry_normalizes_absolute_path_and_requires_utc(tmp_path):
    entry = RecentSessionEntry(tmp_path / "missing.session", datetime(2026, 1, 1, tzinfo=UTC))
    assert Path(entry.path).is_absolute()
    assert not Path(entry.path).exists()
    with pytest.raises(ValueError, match="UTC"):
        RecentSessionEntry("x", datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="UTC"):
        RecentSessionEntry("x", datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))))


def test_recent_entries_deduplicate_sort_cap_and_remove(tmp_path, monkeypatch):
    entries = tuple(
        RecentSessionEntry(tmp_path / f"{index}.json", datetime(2026, 1, 1, index, tzinfo=UTC))
        for index in range(MAX_RECENT_SESSIONS + 2)
    )
    monkeypatch.setattr("bootloader_upgrade_tool.gui.persistence_models.os.path.normcase", lambda value: value.lower())
    duplicate = RecentSessionEntry(str(tmp_path / "0.JSON"), datetime(2026, 1, 2, tzinfo=UTC))
    cache = RuntimeCacheDocument(recent_sessions=(*entries, duplicate))
    assert len(cache.recent_sessions) == MAX_RECENT_SESSIONS
    assert cache.recent_sessions[0] == duplicate
    assert cache.without_recent_session(str(tmp_path / "0.json")).recent_sessions[0] != duplicate
    assert cache.without_recent_session(tmp_path / "absent") == cache


@pytest.mark.parametrize(
    "model",
    [
        TargetSessionSettings(RuntimeCpuId.CPU1), SessionDocument(), GlobalCommandSettings(),
        GlobalSettingsDocument(), RuntimeCacheDocument(),
    ],
)
def test_models_are_frozen_and_slotted(model):
    assert not hasattr(model, "__dict__")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        setattr(model, fields(model)[0].name, None)


def test_persistence_modules_do_not_depend_on_qt():
    root = Path(__file__).parents[2] / "pc" / "src" / "bootloader_upgrade_tool" / "gui"
    for name in ("persistence_models.py", "persistence_stores.py", "session_application_service.py"):
        assert "PySide6" not in (root / name).read_text(encoding="utf-8")
