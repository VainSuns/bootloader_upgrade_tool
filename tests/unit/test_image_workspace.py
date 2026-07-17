from pathlib import Path

import pytest

from bootloader_upgrade_tool.image_workspace import (
    ImageMaterializationWorkspace,
    ImageWorkspaceStateError,
    Sci8Workspace,
)


def test_sci8_workspace_is_lazy_unique_and_cleans_only_children(tmp_path) -> None:
    root = tmp_path / "root"
    first, second = Sci8Workspace(root), Sci8Workspace(root)
    assert not root.exists()
    with pytest.raises(ImageWorkspaceStateError):
        _ = first.path
    with first, second:
        first_path, second_path = first.path, second.path
        assert first_path != second_path
        assert first_path.parent == root and second_path.parent == root
        assert first_path.name.startswith("sci8_")
        output = first.output_path("same.out")
        assert output == first_path / "same.sci8.txt"
        output.write_text("generated", encoding="utf-8")
    assert root.is_dir()
    assert not first_path.exists() and not second_path.exists()
    with pytest.raises(ImageWorkspaceStateError):
        first.output_path("same.out")
    first.close()


def test_materialization_workspace_cleans_on_success_and_exception(tmp_path) -> None:
    root = tmp_path / "root"
    with ImageMaterializationWorkspace(tmp_path / "image.out", root) as materialization:
        child = materialization.workspace_path
        assert materialization.requires_conversion
        assert child is not None and materialization.sci8_path.parent == child
        materialization.sci8_path.write_text("generated", encoding="utf-8")
    assert child is not None and not child.exists()

    with pytest.raises(RuntimeError, match="cancelled"):
        with ImageMaterializationWorkspace(tmp_path / "image.out", root) as failed:
            failed.sci8_path.write_text("generated", encoding="utf-8")
            failed_child = failed.workspace_path
            raise RuntimeError("cancelled")
    assert failed_child is not None and not failed_child.exists()


def test_txt_materialization_is_direct_read_only_and_creates_no_root(tmp_path) -> None:
    source = tmp_path / "user.txt"
    original = b"user-owned sci8"
    source.write_bytes(original)
    root = tmp_path / "root"
    with ImageMaterializationWorkspace(source, root) as materialization:
        assert materialization.source_path == source
        assert materialization.sci8_path == source
        assert not materialization.requires_conversion
        assert materialization.workspace_path is None
        assert not root.exists()
    assert source.read_bytes() == original


def test_reentry_is_rejected_and_cleanup_error_is_visible(tmp_path, monkeypatch) -> None:
    workspace = Sci8Workspace(tmp_path)
    workspace.__enter__()
    with pytest.raises(ImageWorkspaceStateError, match="already active"):
        workspace.__enter__()
    path = workspace.path
    with monkeypatch.context() as patch:
        patch.setattr("bootloader_upgrade_tool.image_workspace.shutil.rmtree", lambda _path: (_ for _ in ()).throw(OSError("locked")))
        with pytest.raises(OSError, match="locked"):
            workspace.close()
    assert path.exists()
    workspace.close()
