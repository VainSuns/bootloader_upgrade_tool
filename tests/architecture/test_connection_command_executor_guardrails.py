from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FOUNDATION_MODULES = (
    REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui/connection_command_executor.py",
    REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui/connection_maintenance.py",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }


def test_executor_foundation_has_no_gui_or_concrete_transport_dependencies():
    forbidden = ("PySide6", "controller", "task_dialog", "binding", "widgets", "serial_transport")

    for path in FOUNDATION_MODULES:
        imports = _imports(path)
        assert not any(marker in imported for marker in forbidden for imported in imports)


def test_executor_foundation_never_accesses_client_ping_or_qtimer():
    for path in FOUNDATION_MODULES:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

        assert "client" not in attributes
        assert "ping" not in attributes | names
        assert "QTimer" not in source


def test_runtime_backend_owns_the_only_executor_reference():
    gui_dir = REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui"
    owners = []
    for path in gui_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.Attribute) and node.attr == "_connection_command_executor"
            for node in ast.walk(tree)
        ):
            owners.append(path.name)

    assert owners == ["runtime_backend.py"]


def test_views_and_bindings_do_not_reference_executor():
    gui_dir = REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui"
    violations = []
    for path in (*gui_dir.glob("*_binding.py"), *gui_dir.glob("pages/**/*.py"), *gui_dir.glob("widgets/**/*.py")):
        if "connection_command_executor" in path.read_text(encoding="utf-8"):
            violations.append(path.relative_to(REPO_ROOT).as_posix())

    assert not violations
