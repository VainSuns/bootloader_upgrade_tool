"""Operation- and parse-scoped SCI8 workspaces."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


class ImageWorkspaceError(RuntimeError):
    """Base error for image workspace lifecycle failures."""


class ImageWorkspaceStateError(ImageWorkspaceError):
    """An active-only workspace value was accessed outside its lifetime."""


class Sci8Workspace:
    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root).expanduser() if root is not None else None
        self._path: Path | None = None

    def __enter__(self) -> Sci8Workspace:
        if self._path is not None:
            raise ImageWorkspaceStateError("SCI8 workspace is already active")
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)
        self._path = Path(tempfile.mkdtemp(prefix="sci8_", dir=self._root))
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> bool:
        self.close()
        return False

    @property
    def path(self) -> Path:
        if self._path is None:
            raise ImageWorkspaceStateError("SCI8 workspace is not active")
        return self._path

    def output_path(self, source_path: str | Path) -> Path:
        return self.path / f"{Path(source_path).stem}.sci8.txt"

    def close(self) -> None:
        if self._path is not None:
            shutil.rmtree(self._path)
            self._path = None


@dataclass(frozen=True, slots=True)
class ImageMaterialization:
    source_path: Path
    sci8_path: Path
    requires_conversion: bool
    workspace_path: Path | None


class ImageMaterializationWorkspace:
    def __init__(self, source_path: str | Path, root: str | Path | None = None) -> None:
        self._source_path = Path(source_path)
        self._root = root
        self._workspace: Sci8Workspace | None = None
        self._materialization: ImageMaterialization | None = None

    def __enter__(self) -> ImageMaterialization:
        if self._materialization is not None:
            raise ImageWorkspaceStateError("Image materialization workspace is already active")
        if self._source_path.suffix.lower() == ".txt":
            self._materialization = ImageMaterialization(
                self._source_path, self._source_path, False, None
            )
        else:
            self._workspace = Sci8Workspace(self._root)
            self._workspace.__enter__()
            self._materialization = ImageMaterialization(
                self._source_path,
                self._workspace.output_path(self._source_path),
                True,
                self._workspace.path,
            )
        return self._materialization

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False

    def close(self) -> None:
        workspace, self._workspace = self._workspace, None
        self._materialization = None
        if workspace is not None:
            workspace.close()


__all__ = [
    "ImageMaterialization",
    "ImageMaterializationWorkspace",
    "ImageWorkspaceError",
    "ImageWorkspaceStateError",
    "Sci8Workspace",
]
