from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bootloader_upgrade_tool.gui.persistence_models import (
    MAX_RECENT_SESSIONS,
    RuntimeCacheDocument,
    SessionDocument,
)
from bootloader_upgrade_tool.gui.persistence_stores import (
    PersistenceWriteError,
    RuntimeCacheStore,
    SessionStore,
)
from bootloader_upgrade_tool.gui.session_application_service import (
    SessionApplicationService,
    SessionPathRequiredError,
)


UTC = timezone.utc


def _service(tmp_path, clock=None):
    return SessionApplicationService(
        SessionStore(), RuntimeCacheStore(tmp_path / "cache" / "runtime_cache.json"),
        clock or (lambda: datetime(2026, 1, 1, tzinfo=UTC)),
    )


def _changed(document):
    return replace(document, selected_transport="tcp", transport_configs={"tcp": {"host": "127.0.0.1"}})


def test_constructor_is_clean_untitled_without_creating_files(tmp_path):
    service = _service(tmp_path)
    assert service.state.document == SessionDocument()
    assert service.state.path is None
    assert service.state.is_dirty is False
    assert service.state.display_name == "Untitled"
    assert not list(tmp_path.rglob("*"))
    assert service.state.document.target_settings


def test_new_untitled_resets_without_session_or_cache_io(tmp_path):
    service = _service(tmp_path)
    service.replace_document(_changed(service.state.document))
    service.new_untitled()
    assert service.state == type(service.state)(SessionDocument(), None, False, "Untitled")
    assert not list(tmp_path.rglob("*"))


def test_replace_document_tracks_baseline(tmp_path):
    service = _service(tmp_path)
    baseline = service.state.document
    changed = _changed(baseline)
    assert service.replace_document(changed).is_dirty
    assert not service.replace_document(baseline).is_dirty
    with pytest.raises(TypeError):
        service.replace_document(object())


def test_open_success_is_absolute_clean_and_does_not_change_recent(tmp_path):
    path = tmp_path / "saved.session"
    SessionStore().save(path, _changed(SessionDocument()))
    service = _service(tmp_path)
    before = service.recent_sessions()
    state = service.open(path)
    assert state.path == path.resolve()
    assert state.display_name == path.name
    assert not state.is_dirty
    assert service.recent_sessions() == before


@pytest.mark.parametrize("missing", [True, False])
def test_open_failure_preserves_exact_state(tmp_path, missing):
    service = _service(tmp_path)
    service.replace_document(_changed(service.state.document))
    before = service.state
    path = tmp_path / "bad.session"
    if not missing:
        path.write_text("not json", encoding="utf-8")
    with pytest.raises(Exception):
        service.open(path)
    assert service.state is before


def test_save_on_untitled_requires_path(tmp_path):
    with pytest.raises(SessionPathRequiredError):
        _service(tmp_path).save()


def test_save_as_and_save_use_clock_deduplicate_and_reorder(tmp_path):
    times = iter(datetime(2026, 1, day, tzinfo=UTC) for day in (1, 2, 3))
    service = _service(tmp_path, lambda: next(times))
    first = tmp_path / "first.session"
    second = tmp_path / "second.session"
    result = service.save_as(first)
    assert result.state.path == first.resolve() and not result.state.is_dirty
    assert not result.warnings
    service.save_as(second)
    service.save_as(first)
    assert [Path(entry.path).name for entry in service.recent_sessions()] == ["first.session", "second.session"]
    assert service.recent_sessions()[0].last_saved_at_utc == datetime(2026, 1, 3, tzinfo=UTC)
    assert SessionStore().load(first).document == service.state.document


def test_recent_list_caps_retains_missing_and_removes_explicitly(tmp_path):
    counter = iter(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index) for index in range(20))
    service = _service(tmp_path, lambda: next(counter))
    for index in range(MAX_RECENT_SESSIONS + 2):
        service.save_as(tmp_path / f"missing-{index}.session")
    assert len(service.recent_sessions()) == MAX_RECENT_SESSIONS
    removed = Path(service.recent_sessions()[0].path)
    removed.unlink()
    assert removed in tuple(Path(entry.path) for entry in service.recent_sessions())
    state = service.state
    service.remove_recent_session(removed)
    assert removed not in tuple(Path(entry.path) for entry in service.recent_sessions())
    assert service.state is state
    service.remove_recent_session(tmp_path / "not-listed")


class _FailingSessionStore(SessionStore):
    def save(self, path, document):
        raise PersistenceWriteError("session failed")


class _FailingCacheStore(RuntimeCacheStore):
    def save(self, document):
        raise PersistenceWriteError("cache failed")


def test_session_save_failure_preserves_state_and_cache(tmp_path):
    cache_store = RuntimeCacheStore(tmp_path / "cache.json")
    service = SessionApplicationService(_FailingSessionStore(), cache_store)
    service.replace_document(_changed(service.state.document))
    before = service.state
    with pytest.raises(PersistenceWriteError, match="session failed"):
        service.save_as(tmp_path / "session.json")
    assert service.state is before
    assert service.recent_sessions() == ()
    assert not cache_store.path.exists()


def test_cache_failure_after_session_save_returns_warning_and_clean_state(tmp_path):
    session_path = tmp_path / "session.json"
    service = SessionApplicationService(
        SessionStore(), _FailingCacheStore(tmp_path / "cache.json"),
        lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    service.replace_document(_changed(service.state.document))
    result = service.save_as(session_path)
    assert session_path.exists()
    assert not result.state.is_dirty
    assert result.warnings == ("Runtime Cache update failed: cache failed",)
    assert service.recent_sessions() == ()


def test_clock_failure_after_session_save_is_also_only_a_warning(tmp_path):
    session_path = tmp_path / "session.json"
    service = _service(tmp_path, lambda: (_ for _ in ()).throw(RuntimeError("clock failed")))
    result = service.save_as(session_path)
    assert session_path.exists() and not result.state.is_dirty
    assert result.warnings == ("Runtime Cache update failed: clock failed",)


def test_service_module_has_no_forbidden_runtime_or_qt_imports():
    source = (Path(__file__).parents[2] / "pc" / "src" / "bootloader_upgrade_tool" / "gui" / "session_application_service.py").read_text(encoding="utf-8")
    for forbidden in ("PySide6", "RuntimeBackend", "Controller", "Binding", "transport", "operations", "runtime_v2_events"):
        assert forbidden not in source
