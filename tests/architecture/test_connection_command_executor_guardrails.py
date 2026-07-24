from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FOUNDATION_MODULES = (
    REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui/connection_command_executor.py",
    REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui/connection_maintenance.py",
)
RUNTIME_BACKEND = REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui/runtime_backend.py"


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


def test_connected_runtime_paths_share_the_foreground_helper():
    tree = ast.parse(RUNTIME_BACKEND.read_text(encoding="utf-8"))
    functions = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }

    helper_calls = {
        node.func.attr
        for node in ast.walk(functions["_execute_connected_foreground"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "execute_foreground" in helper_calls
    for name in (
        "_call_status_operation",
        "_execute_ram_operation",
        "_execute_advanced_flash_operation",
        "_execute_advanced_metadata_operation",
    ):
        calls = {
            node.func.attr
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "_execute_connected_foreground" in calls


def test_contexts_never_use_captured_session_and_readback_never_nests_a_lease():
    tree = ast.parse(RUNTIME_BACKEND.read_text(encoding="utf-8"))
    functions = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }

    direct_captured_sessions = [
        subscript
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id in {"OperationContext", "FlashOperationContext"}
        for subscript in ast.walk(call)
        if isinstance(subscript, ast.Subscript)
        and isinstance(subscript.value, ast.Name)
        and subscript.value.id == "captured"
        and isinstance(subscript.slice, ast.Constant)
        and subscript.slice.value == 0
    ]
    assert not direct_captured_sessions
    readback_calls = {
        node.func.attr
        for node in ast.walk(functions["_refresh_metadata_after_write"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "execute_foreground" not in readback_calls
    assert "_execute_connected_foreground" not in readback_calls
