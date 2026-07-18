from pathlib import Path

import pytest

from bootloader_upgrade_tool.image_workspace import (
    ImageMaterialization,
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

    with pytest.raises(RuntimeError, match="cancelled") as caught:
        with ImageMaterializationWorkspace(tmp_path / "image.out", root) as failed:
            failed.sci8_path.write_text("generated", encoding="utf-8")
            failed_child = failed.workspace_path
            raise RuntimeError("cancelled")
    assert failed_child is not None and not failed_child.exists()
    assert str(caught.value) == "cancelled"
    assert not getattr(caught.value, "__notes__", ())


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


def test_out_operation_success_cleanup(tmp_path) -> None:
    source, root = tmp_path / "service.out", tmp_path / "work"
    source.write_text("source")
    with ImageMaterializationWorkspace(source, root) as materialization:
        child = materialization.workspace_path
        materialization.sci8_path.write_text("generated")
    assert child is not None and not child.exists()


def test_out_operation_failure_cleanup(tmp_path) -> None:
    source, root = tmp_path / "service.out", tmp_path / "work"
    source.write_text("source")
    child = None
    with pytest.raises(RuntimeError, match="failed"):
        with ImageMaterializationWorkspace(source, root) as materialization:
            child = materialization.workspace_path
            raise RuntimeError("failed")
    assert child is not None and not child.exists()


def test_out_operation_cancel_cleanup(tmp_path) -> None:
    source, root = tmp_path / "service.out", tmp_path / "work"
    source.write_text("source")

    def cancelled():
        with ImageMaterializationWorkspace(source, root) as materialization:
            return "cancelled", materialization.workspace_path

    status, child = cancelled()
    assert status == "cancelled" and child is not None and not child.exists()


def test_txt_operation_is_read_only_and_creates_no_workspace(tmp_path) -> None:
    source, root = tmp_path / "service.txt", tmp_path / "work"
    source.write_text("source")
    before = source.read_bytes()
    with ImageMaterializationWorkspace(source, root) as materialization:
        assert materialization.sci8_path == source
        assert materialization.workspace_path is None
    assert source.read_bytes() == before
    assert not root.exists()


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


def test_materialization_cleanup_failure_retains_retry_state(tmp_path, monkeypatch) -> None:
    workspace = ImageMaterializationWorkspace(tmp_path / "image.out", tmp_path / "root")
    with monkeypatch.context() as patch:
        patch.setattr(
            "bootloader_upgrade_tool.image_workspace.shutil.rmtree",
            lambda _path: (_ for _ in ()).throw(OSError("cleanup locked")),
        )
        with pytest.raises(OSError, match="cleanup locked"):
            with workspace as materialization:
                child = materialization.workspace_path
    assert workspace._workspace is not None
    assert workspace._materialization is materialization
    assert child is not None and child.exists()

    workspace.close()
    assert workspace._workspace is None and workspace._materialization is None
    assert not child.exists()
    workspace.close()


def test_materialization_primary_exception_survives_cleanup_failure_and_retry(
    tmp_path, monkeypatch
) -> None:
    workspace = ImageMaterializationWorkspace(tmp_path / "image.out", tmp_path / "root")
    with monkeypatch.context() as patch:
        patch.setattr(
            "bootloader_upgrade_tool.image_workspace.shutil.rmtree",
            lambda _path: (_ for _ in ()).throw(OSError("cleanup locked")),
        )
        with pytest.raises(RuntimeError, match="primary failure") as caught:
            with workspace as materialization:
                child = materialization.workspace_path
                raise RuntimeError("primary failure")
    notes = "\n".join(caught.value.__notes__)
    assert "OSError" in notes and "cleanup locked" in notes
    assert workspace._workspace is not None and workspace._materialization is materialization
    assert child is not None and child.exists()

    workspace.close()
    assert not child.exists()


def test_sci8_context_preserves_primary_when_cleanup_also_fails(tmp_path, monkeypatch) -> None:
    workspace = Sci8Workspace(tmp_path / "root")
    with monkeypatch.context() as patch:
        patch.setattr(
            "bootloader_upgrade_tool.image_workspace.shutil.rmtree",
            lambda _path: (_ for _ in ()).throw(OSError("cleanup locked")),
        )
        with pytest.raises(RuntimeError, match="primary failure") as caught:
            with workspace:
                child = workspace.path
                raise RuntimeError("primary failure")
    assert "OSError: cleanup locked" in "\n".join(caught.value.__notes__)
    assert workspace.path == child and child.exists()
    workspace.close()
    assert not child.exists()


def test_sci8_context_cleanup_failure_propagates_and_can_retry(tmp_path, monkeypatch) -> None:
    workspace = Sci8Workspace(tmp_path / "root")
    with monkeypatch.context() as patch:
        patch.setattr(
            "bootloader_upgrade_tool.image_workspace.shutil.rmtree",
            lambda _path: (_ for _ in ()).throw(OSError("cleanup locked")),
        )
        with pytest.raises(OSError, match="cleanup locked"):
            with workspace:
                child = workspace.path
    assert workspace.path == child and child.exists()
    workspace.close()
    assert not child.exists()


@pytest.mark.parametrize(
    ("args", "error"),
    (
        (("source", Path("source"), False, None), TypeError),
        ((Path("source"), "source", False, None), TypeError),
        ((Path("source"), Path("source"), 1, None), TypeError),
        ((Path("source"), Path("source"), False, "workspace"), TypeError),
        ((Path("source"), Path("other"), False, None), ValueError),
        ((Path("source"), Path("source"), False, Path("workspace")), ValueError),
        ((Path("source"), Path("output"), True, None), ValueError),
        ((Path("source"), Path("workspace"), True, Path("workspace")), ValueError),
        ((Path("source"), Path("outside/output"), True, Path("workspace")), ValueError),
    ),
)
def test_image_materialization_rejects_inconsistent_state(args, error) -> None:
    with pytest.raises(error):
        ImageMaterialization(*args)


def test_image_materialization_accepts_valid_direct_and_conversion_values(tmp_path) -> None:
    source = tmp_path / "source.txt"
    direct = ImageMaterialization(source, source, False, None)
    workspace = tmp_path / "workspace"
    converted = ImageMaterialization(
        tmp_path / "source.out", workspace / "source.sci8.txt", True, workspace
    )
    assert not direct.requires_conversion
    assert converted.workspace_path == workspace
