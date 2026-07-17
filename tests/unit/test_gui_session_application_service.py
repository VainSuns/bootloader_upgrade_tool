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
    PersistenceFormatError,
    PersistenceWriteError,
    RuntimeCacheStore,
    SessionStore,
    UnsupportedSchemaVersionError,
)
from bootloader_upgrade_tool.gui.session_application_service import (
    SessionApplicationService,
    SessionPathRequiredError,
    SessionSwitchCandidate,
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


def test_prepare_new_is_non_mutating_and_commit_installs_clean_candidate(tmp_path):
    service = _service(tmp_path)
    service.replace_document(_changed(service.state.document))
    before = service.state
    candidate = service.prepare_new_untitled()
    assert candidate == SessionSwitchCandidate(SessionDocument(), None, "Untitled")
    assert service.state is before
    committed = service.commit_switch(candidate)
    assert committed == type(committed)(SessionDocument(), None, False, "Untitled")
    assert not service.replace_document(SessionDocument()).is_dirty


@pytest.mark.parametrize(
    "factory",
    (
        lambda: SessionSwitchCandidate(object(), None, "Untitled"),
        lambda: SessionSwitchCandidate(SessionDocument(), "path", "Saved"),
        lambda: SessionSwitchCandidate(SessionDocument(), None, ""),
    ),
)
def test_switch_candidate_rejects_invalid_values(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_prepare_open_normalizes_and_loads_without_mutating(tmp_path):
    path = tmp_path / "saved.session"
    document = _changed(SessionDocument())
    SessionStore().save(path, document)
    service = _service(tmp_path)
    before = service.state
    candidate = service.prepare_open(path)
    assert candidate.document == document
    assert candidate.path == path.resolve() and candidate.display_name == path.name
    assert service.state is before
    assert service.commit_switch(candidate).document == document


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


class _TrackingBrokenCacheStore(RuntimeCacheStore):
    def __init__(self, path, error):
        super().__init__(path)
        self.error = error
        self.save_calls = 0

    def load(self):
        raise self.error

    def save(self, document):
        self.save_calls += 1
        raise PersistenceWriteError("cache still broken")


class _ProgrammingErrorCacheStore(RuntimeCacheStore):
    def load(self):
        raise RuntimeError("programming error")


def test_runtime_cache_programming_error_is_not_hidden(tmp_path):
    with pytest.raises(RuntimeError, match="programming error"):
        SessionApplicationService(
            SessionStore(), _ProgrammingErrorCacheStore(tmp_path / "cache.json")
        )


@pytest.mark.parametrize(
    ("payload", "error"),
    (
        (b"not json", PersistenceFormatError("original cache error")),
        (
            b'{"schema_version": 999, "recent_sessions": []}',
            UnsupportedSchemaVersionError("original cache error"),
        ),
    ),
)
def test_broken_runtime_cache_recovers_without_rewriting_and_later_save_attempts_update(
    tmp_path, payload, error
):
    cache_path = tmp_path / "cache.json"
    cache_path.write_bytes(payload)
    store = _TrackingBrokenCacheStore(cache_path, error)
    service = SessionApplicationService(SessionStore(), store)
    assert service.state == type(service.state)(SessionDocument(), None, False, "Untitled")
    assert service.recent_sessions() == ()
    assert service.startup_warnings == ("original cache error",)
    assert cache_path.read_bytes() == payload and store.save_calls == 0
    result = service.save_as(tmp_path / "session.json")
    assert store.save_calls == 1
    assert result.warnings == ("Runtime Cache update failed: cache still broken",)


def test_missing_runtime_cache_has_no_startup_warning(tmp_path):
    service = _service(tmp_path)
    assert service.startup_warnings == ()


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
