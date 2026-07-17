"""File-backed Session lifecycle without GUI or runtime dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .persistence_models import RecentSessionEntry, RuntimeCacheDocument, SessionDocument
from .persistence_stores import PersistenceError, RuntimeCacheStore, SessionStore


class SessionPathRequiredError(PersistenceError):
    pass


@dataclass(frozen=True, slots=True)
class SessionApplicationState:
    document: SessionDocument
    path: Path | None
    is_dirty: bool
    display_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.document, SessionDocument):
            raise TypeError("document must be SessionDocument")
        if self.path is not None and not isinstance(self.path, Path):
            raise TypeError("path must be Path or None")
        if type(self.is_dirty) is not bool:
            raise TypeError("is_dirty must be bool")
        if type(self.display_name) is not str or not self.display_name:
            raise ValueError("display_name must be a non-empty string")


@dataclass(frozen=True, slots=True)
class SessionSaveResult:
    state: SessionApplicationState
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state, SessionApplicationState):
            raise TypeError("state must be SessionApplicationState")
        if any(type(warning) is not str for warning in self.warnings):
            raise TypeError("warnings must contain strings")
        object.__setattr__(self, "warnings", tuple(self.warnings))


def _normalized_path(path: str | Path) -> Path:
    if not isinstance(path, (str, Path)):
        raise TypeError("path must be a string or Path")
    return Path(path).expanduser().resolve(strict=False)


class SessionApplicationService:
    def __init__(
        self,
        session_store: SessionStore | None = None,
        runtime_cache_store: RuntimeCacheStore | None = None,
        utc_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_store = session_store or SessionStore()
        self._runtime_cache_store = runtime_cache_store or RuntimeCacheStore()
        self._clock = utc_clock or (lambda: datetime.now(timezone.utc))
        document = SessionDocument()
        self._state = SessionApplicationState(document, None, False, "Untitled")
        self._baseline = document
        self._runtime_cache = self._runtime_cache_store.load().document

    @property
    def state(self) -> SessionApplicationState:
        return self._state

    def new_untitled(self) -> SessionApplicationState:
        document = SessionDocument()
        self._baseline = document
        self._state = SessionApplicationState(document, None, False, "Untitled")
        return self._state

    def open(self, path: str | Path) -> SessionApplicationState:
        normalized = _normalized_path(path)
        document = self._session_store.load(normalized).document
        state = SessionApplicationState(document, normalized, False, normalized.name)
        self._baseline = document
        self._state = state
        return state

    def replace_document(self, document: SessionDocument) -> SessionApplicationState:
        if not isinstance(document, SessionDocument):
            raise TypeError("document must be SessionDocument")
        self._state = SessionApplicationState(
            document, self._state.path, document != self._baseline, self._state.display_name
        )
        return self._state

    def save(self) -> SessionSaveResult:
        if self._state.path is None:
            raise SessionPathRequiredError("Untitled Session requires save_as(path)")
        return self._save_to(self._state.path)

    def save_as(self, path: str | Path) -> SessionSaveResult:
        return self._save_to(_normalized_path(path))

    def _save_to(self, path: Path) -> SessionSaveResult:
        document = self._state.document
        self._session_store.save(path, document)
        self._baseline = document
        self._state = SessionApplicationState(document, path, False, path.name)
        warnings: tuple[str, ...] = ()
        try:
            candidate = self._runtime_cache.with_recent_session(path, self._clock())
            self._runtime_cache_store.save(candidate)
        except Exception as exc:
            warnings = (f"Runtime Cache update failed: {exc}",)
        else:
            self._runtime_cache = candidate
        return SessionSaveResult(self._state, warnings)

    def recent_sessions(self) -> tuple[RecentSessionEntry, ...]:
        return self._runtime_cache.recent_sessions

    def remove_recent_session(self, path: str | Path) -> tuple[RecentSessionEntry, ...]:
        candidate = self._runtime_cache.without_recent_session(path)
        self._runtime_cache_store.save(candidate)
        self._runtime_cache = candidate
        return candidate.recent_sessions


__all__ = [
    "SessionApplicationService",
    "SessionApplicationState",
    "SessionPathRequiredError",
    "SessionSaveResult",
]
