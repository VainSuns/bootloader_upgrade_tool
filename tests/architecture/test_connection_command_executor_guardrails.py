from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FOUNDATION_MODULES = (
    REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui/connection_command_executor.py",
    REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui/connection_maintenance.py",
)
RUNTIME_BACKEND = REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui/runtime_backend.py"
QT_SCHEDULER = REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui/qt_connection_maintenance.py"
GLOBAL_SETTINGS_BINDING = REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui/global_settings_binding.py"


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


def test_maintenance_contract_has_no_timer_thread_or_gui_dependencies():
    path = REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui/connection_maintenance.py"
    source = path.read_text(encoding="utf-8")
    imports = _imports(path)

    assert not any(
        marker in imported
        for marker in ("PySide6", "controller", "task_dialog", "binding", "advanced")
        for imported in imports
    )
    assert not any(token in source.lower() for token in ("qtimer", "thread", "interval", "retry"))


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


def test_qt_scheduler_only_reaches_maintenance_through_bound_callback():
    source = QT_SCHEDULER.read_text(encoding="utf-8")
    imports = _imports(QT_SCHEDULER)
    tree = ast.parse(source, filename=str(QT_SCHEDULER))
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    assert any(imported.startswith("PySide6") for imported in imports)
    assert not any(
        marker in imported
        for marker in ("runtime_backend", "transport", "session")
        for imported in imports
    )
    assert not {"client", "ping"} & attributes
    assert not {
        "GuiController",
        "TaskDialog",
        "TaskExecutionResult",
        "request_task",
        "SerialTransport",
        "UpgradeSession",
    } & (names | attributes)


def test_qt_scheduler_executor_lifetime_is_detached_and_nonblocking():
    source = QT_SCHEDULER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(QT_SCHEDULER))
    pool_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "QThreadPool"
    ]
    pool_owners = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(call in set(ast.walk(node)) for call in pool_calls)
    }
    exported = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    )
    exported_names = {
        element.value
        for element in exported.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }

    assert pool_calls and all(not call.args and not call.keywords for call in pool_calls)
    assert pool_owners and all(name.startswith("_") for name in pool_owners)
    assert pool_owners.isdisjoint(exported_names)
    assert not any(
        token in source
        for token in ("waitForDone", "threading.Timer", "time.sleep", "QThreadPool(self)")
    )


def test_views_and_bindings_do_not_own_ping_execution_resources():
    gui_dir = REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui"
    violations = []
    for path in (
        *gui_dir.glob("*_binding.py"),
        *gui_dir.glob("pages/**/*.py"),
        *gui_dir.glob("widgets/**/*.py"),
    ):
        source = path.read_text(encoding="utf-8")
        if "QThreadPool" in source or "PingExecutionHost" in source:
            violations.append(path.relative_to(REPO_ROOT).as_posix())

    assert not violations


def test_app_is_the_only_production_qt_scheduler_composition_root():
    gui_dir = REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui"
    owners = [
        path.name
        for path in gui_dir.rglob("*.py")
        if path != QT_SCHEDULER
        and "QtConnectionMaintenanceScheduler" in path.read_text(encoding="utf-8")
    ]
    assert owners == ["app.py"]


def test_global_settings_binding_uses_only_injected_auto_ping_setter():
    source = GLOBAL_SETTINGS_BINDING.read_text(encoding="utf-8")
    imports = _imports(GLOBAL_SETTINGS_BINDING)
    assert not any("qt_connection_maintenance" in imported for imported in imports)
    assert "QtConnectionMaintenanceScheduler" not in source
    assert "_maintenance_scheduler" not in source


def test_qt_scheduler_exposes_no_generic_auto_ping_controls():
    source = QT_SCHEDULER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(QT_SCHEDULER))
    scheduler = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "QtConnectionMaintenanceScheduler"
    )
    methods = {node.name for node in scheduler.body if isinstance(node, ast.FunctionDef)}
    assert "set_auto_ping_enabled" in methods
    assert not {"set_interval", "pause", "resume"} & methods
    assert "DEFAULT_AUTO_PING_INTERVAL_MS = 2000" in source


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
    helper_strings = {
        node.value
        for node in ast.walk(functions["_execute_connected_foreground"])
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert {
        "foreground_command_started",
        "protocol_activity",
        "foreground_command_finished",
    } <= helper_strings
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


def test_maintenance_ping_stays_inside_executor_and_outside_task_publication():
    tree = ast.parse(RUNTIME_BACKEND.read_text(encoding="utf-8"))
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "try_execute_maintenance_ping"
    )
    action = next(
        node
        for node in method.body
        if isinstance(node, ast.FunctionDef) and node.name == "ping"
    )
    lease_call = next(
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "try_execute_maintenance"
    )
    all_ping_accesses = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Attribute) and node.attr == "ping"
    ]
    action_ping_accesses = [
        node
        for node in ast.walk(action)
        if isinstance(node, ast.Attribute) and node.attr == "ping"
    ]
    attributes = {
        node.attr for node in ast.walk(method) if isinstance(node, ast.Attribute)
    }
    names = {node.id for node in ast.walk(method) if isinstance(node, ast.Name)}

    assert isinstance(lease_call.args[1], ast.Name) and lease_call.args[1].id == "ping"
    assert all_ping_accesses == action_ping_accesses and len(all_ping_accesses) == 1
    assert "_publish" not in attributes
    assert not {
        "TaskExecutionResult",
        "GuiController",
        "TaskDialog",
        "SharedResult",
        "request_task",
    } & (names | attributes)
