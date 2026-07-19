import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bootloader_upgrade_tool.gui.persistence_models import (
    GlobalCommandSettings,
    GlobalSettingsDocument,
    RecentSessionEntry,
    RuntimeCacheDocument,
    SessionDocument,
)
from bootloader_upgrade_tool.gui.persistence_stores import (
    GlobalSettingsStore,
    PersistenceFileNotFoundError,
    PersistenceFormatError,
    PersistenceWriteError,
    RuntimeCacheStore,
    SessionStore,
    UnsupportedSchemaVersionError,
    default_persistence_paths,
)


UTC = timezone.utc


def _stores(tmp_path):
    return (
        (SessionStore(), tmp_path / "session.json", SessionDocument(), lambda store, path, doc: store.save(path, doc), lambda store, path: store.load(path)),
        (GlobalSettingsStore(tmp_path / "global.json"), tmp_path / "global.json", GlobalSettingsDocument(), lambda store, path, doc: store.save(doc), lambda store, path: store.load()),
        (RuntimeCacheStore(tmp_path / "cache.json"), tmp_path / "cache.json", RuntimeCacheDocument(), lambda store, path, doc: store.save(doc), lambda store, path: store.load()),
    )


@pytest.mark.parametrize("kind", range(3))
def test_round_trip_is_deterministic_atomic_and_domain_isolated(tmp_path, kind):
    store, path, document, save, load = _stores(tmp_path)[kind]
    save(store, path, document)
    first = path.read_bytes()
    assert first.endswith(b"\n")
    assert b"\r\n" not in first
    save(store, path, document)
    assert path.read_bytes() == first
    assert load(store, path).document == document
    keys = set(json.loads(first))
    assert keys == (
        {"schema_version", "selected_transport", "transport_configs", "target_settings"},
        {"schema_version", "hex2000_executable_path", "command", "log_output_path"},
        {"schema_version", "recent_sessions"},
    )[kind]


def test_non_ascii_sorted_json_and_utc_z(tmp_path):
    global_path = tmp_path / "global.json"
    GlobalSettingsStore(global_path).save(GlobalSettingsDocument(hex2000_executable_path="工具.exe"))
    text = global_path.read_text(encoding="utf-8")
    assert "工具.exe" in text
    cache_path = tmp_path / "cache.json"
    RuntimeCacheStore(cache_path).save(RuntimeCacheDocument(recent_sessions=(
        RecentSessionEntry(tmp_path / "x", datetime(2026, 1, 1, tzinfo=UTC)),
    )))
    assert "2026-01-01T00:00:00Z" in cache_path.read_text(encoding="utf-8")


def test_memory_runtime_state_is_absent_from_every_persistence_domain(tmp_path):
    for store, path, document, save, _load in _stores(tmp_path):
        save(store, path, document)
        text = path.read_text(encoding="utf-8").lower()
        assert all(
            field not in text
            for field in ("memory_states", "freshness", "read_error", "read_at")
        )


def test_missing_file_behavior_does_not_create_files_or_directories(tmp_path):
    with pytest.raises(PersistenceFileNotFoundError):
        SessionStore().load(tmp_path / "missing" / "session.json")
    global_store = GlobalSettingsStore(tmp_path / "missing" / "global.json")
    cache_store = RuntimeCacheStore(tmp_path / "missing" / "cache.json")
    assert global_store.load().source_schema_version is None
    assert cache_store.load().source_schema_version is None
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("kind", range(3))
def test_save_creates_parent_and_temp_in_destination(tmp_path, monkeypatch, kind):
    store, path, document, save, _ = _stores(tmp_path / "nested")[kind]
    observed = []
    from bootloader_upgrade_tool.gui import persistence_stores as module
    original = module.tempfile.NamedTemporaryFile

    def recording_temp(*args, **kwargs):
        observed.append(Path(kwargs["dir"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", recording_temp)
    save(store, path, document)
    assert observed == [path.parent]
    assert path.exists()


@pytest.mark.parametrize("kind", range(3))
def test_replace_failure_preserves_destination_and_cleans_temp(tmp_path, monkeypatch, kind):
    store, path, document, save, _ = _stores(tmp_path)[kind]
    path.write_bytes(b"previous")
    monkeypatch.setattr("bootloader_upgrade_tool.gui.persistence_stores.os.replace", lambda *_: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(PersistenceWriteError, match="replace failed"):
        save(store, path, document)
    assert path.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("kind", range(3))
def test_serialization_failure_preserves_destination(tmp_path, kind):
    store, path, _, save, _ = _stores(tmp_path)[kind]
    path.write_bytes(b"previous")
    with pytest.raises(PersistenceWriteError, match="serialize"):
        save(store, path, object())
    assert path.read_bytes() == b"previous"


@pytest.mark.parametrize("kind", range(3))
def test_write_failure_preserves_destination_and_cleans_temp(tmp_path, monkeypatch, kind):
    store, path, document, save, _ = _stores(tmp_path)[kind]
    path.write_bytes(b"previous")
    from bootloader_upgrade_tool.gui import persistence_stores as module
    original = module.tempfile.NamedTemporaryFile

    class FailingFile:
        def __init__(self, file):
            self.file = file
            self.name = file.name

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()

        def write(self, _payload):
            raise OSError("write failed")

    monkeypatch.setattr(
        module.tempfile, "NamedTemporaryFile",
        lambda *args, **kwargs: FailingFile(original(*args, **kwargs)),
    )
    with pytest.raises(PersistenceWriteError, match="write failed"):
        save(store, path, document)
    assert path.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("kind", range(3))
def test_malformed_unknown_and_future_files_are_explicit_and_unchanged(tmp_path, kind):
    store, path, document, save, load = _stores(tmp_path)[kind]
    save(store, path, document)
    for payload, error in (
        (b"[]", PersistenceFormatError),
        (b'{"schema_version": 999}', UnsupportedSchemaVersionError),
    ):
        path.write_bytes(payload)
        with pytest.raises(error):
            load(store, path)
        assert path.read_bytes() == payload
    data = json.loads(json.dumps(json.loads(_valid_bytes(store, path, document, save))))
    data["unknown"] = 1
    payload = json.dumps(data).encode()
    path.write_bytes(payload)
    with pytest.raises(PersistenceFormatError, match="unknown"):
        load(store, path)
    assert path.read_bytes() == payload


def _valid_bytes(store, path, document, save):
    save(store, path, document)
    return path.read_text(encoding="utf-8")


def test_legacy_global_settings_migrates_in_memory_with_notices(tmp_path):
    path = tmp_path / "legacy.json"
    legacy = {
        "schema_version": 1,
        "hex2000": {"executable_path": " hex2000.exe "},
        "flash_lib": {"descriptor_symbol": "legacy"},
        "temporary_files": {"sci8_temp_dir": "tmp"},
        "connection_timeouts": {"tx_timeout_ms": 1},
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    before = path.read_bytes()
    store = GlobalSettingsStore(path)
    result = store.load()
    assert result.source_schema_version == 1 and result.migrated
    assert result.document == GlobalSettingsDocument(hex2000_executable_path="hex2000.exe")
    assert result.document.command == GlobalCommandSettings()
    assert result.notices == (
        "flash_lib belongs to application resources and is not persisted in Global Settings v2",
        "temporary_files is not persisted in Global Settings v2",
        "connection_timeouts is transport-specific and is not persisted in Global Settings v2",
    )
    assert path.read_bytes() == before
    store.save(result.document)
    saved = path.read_text(encoding="utf-8")
    assert all(name not in saved for name in ("flash_lib", "temporary_files", "connection_timeouts", "descriptor_symbol"))


def test_malformed_legacy_hex2000_fails_without_rewrite(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text('{"schema_version": 1, "hex2000": []}', encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(PersistenceFormatError, match="hex2000"):
        GlobalSettingsStore(path).load()
    assert path.read_bytes() == before


def test_invalid_utf8_is_a_typed_format_error_and_is_not_rewritten(tmp_path):
    path = tmp_path / "session.json"
    path.write_bytes(b"\xff")
    with pytest.raises(PersistenceFormatError, match="UTF-8"):
        SessionStore().load(path)
    assert path.read_bytes() == b"\xff"


def test_default_path_resolution_does_not_create_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("bootloader_upgrade_tool.gui.persistence_stores.sys.platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    paths = default_persistence_paths("app")
    assert paths.global_settings_path == tmp_path / "app" / "global_settings.json"
    assert paths.runtime_cache_path == tmp_path / "app" / "runtime_cache.json"
    assert not (tmp_path / "app").exists()
