from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path
import tomllib


ROOT = Path(__file__).parents[2]
CLI_ROOT = ROOT / "pc" / "src" / "bootloader_upgrade_tool" / "cli"

_FORBIDDEN_IMPORT_ROOTS = (
    "bootloader_upgrade_tool.gui",
    "bootloader_upgrade_tool.tools",
    "bootloader_upgrade_tool.io",
)
_LEGACY_IMPORT_ROOTS = (
    "core.UpgradeWorkflow",
    "tools.cpu1_upgrade",
    "tools.common_cli",
    "io.SerialIoDevice",
)


def _package_for(path: Path) -> str:
    relative = path.relative_to(CLI_ROOT)
    parts = ("bootloader_upgrade_tool", "cli", *relative.parent.parts)
    return ".".join(parts)


def _without_package_prefix(module: str) -> str:
    prefix = "bootloader_upgrade_tool."
    return module[len(prefix) :] if module.startswith(prefix) else module


def _is_forbidden_import(module: str, imported_names: set[str] | None = None) -> bool:
    if imported_names is None:
        imported_names = set()
    if any(module == root or module.startswith(f"{root}.") for root in _FORBIDDEN_IMPORT_ROOTS):
        return True

    legacy_module = _without_package_prefix(module)
    if any(
        legacy_module == root or legacy_module.startswith(f"{root}.")
        for root in _LEGACY_IMPORT_ROOTS
    ):
        return True
    if legacy_module == "core" or legacy_module.startswith("core."):
        return "UpgradeWorkflow" in imported_names
    if legacy_module == "tools" or legacy_module.startswith("tools."):
        return bool(imported_names & {"cpu1_upgrade", "common_cli"})
    if legacy_module == "io" or legacy_module.startswith("io."):
        return "SerialIoDevice" in imported_names
    return False


def forbidden_imports(tree: ast.AST, *, package: str) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_import(alias.name):
                    violations.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                try:
                    module = resolve_name("." * node.level + module, package)
                except ImportError:
                    module = "." * node.level + module
            imported_names = {alias.name for alias in node.names}
            candidates = [module]
            candidates.extend(
                f"{module}.{name}" for name in imported_names if name != "*"
            )
            for candidate in candidates:
                if _is_forbidden_import(candidate, imported_names):
                    violations.append(candidate)
                    break
    return violations


def direct_transact_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "transact")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "transact")
        )
    ]


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    return modules


def test_cli_has_no_gui_legacy_or_low_level_architecture_imports() -> None:
    violations: list[str] = []
    for path in CLI_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(f"{path}: {module}" for module in forbidden_imports(tree, package=_package_for(path)))
        violations.extend(f"{path}: direct transact call" for _ in direct_transact_calls(tree))
    assert not violations

    text = "\n".join(path.read_text(encoding="utf-8") for path in CLI_ROOT.rglob("*.py"))
    for forbidden in ("BootProtocolClient", "Command."):
        assert forbidden not in text


def test_forbidden_import_detector_catches_relative_imports() -> None:
    tree = ast.parse("from ..gui import runtime_backend")
    assert forbidden_imports(tree, package="bootloader_upgrade_tool.cli")


def test_forbidden_import_detector_catches_absolute_imports() -> None:
    tree = ast.parse("from bootloader_upgrade_tool.gui import runtime_backend")
    assert forbidden_imports(tree, package="bootloader_upgrade_tool.cli")


def test_direct_transact_detector_catches_name_calls() -> None:
    tree = ast.parse("transact(request)")
    assert direct_transact_calls(tree)


def test_direct_transact_detector_catches_attribute_calls() -> None:
    tree = ast.parse("session.client.transact(request)")
    assert direct_transact_calls(tree)


def test_detectors_allow_public_operation_imports() -> None:
    tree = ast.parse("from ..operations import memory_read")
    assert not forbidden_imports(tree, package="bootloader_upgrade_tool.cli")
    assert not direct_transact_calls(tree)


def test_cli_layer_dependencies_stay_on_the_declared_boundaries() -> None:
    commands_modules = imported_modules(CLI_ROOT / "commands.py")
    runtime_modules = imported_modules(CLI_ROOT / "runtime.py")
    output_modules = imported_modules(CLI_ROOT / "output.py")

    assert any(module.endswith("operations") for module in commands_modules)
    assert not any("transport" in module or "protocol" in module for module in commands_modules)
    assert any(module.endswith("session") for module in runtime_modules)
    assert any(module.endswith("transport") for module in runtime_modules)
    assert not any("transport" in module or "protocol" in module for module in output_modules)
    assert any(module.endswith("operations") for module in output_modules)


def test_gui_module_entry_remains_the_gui_entry() -> None:
    gui_entry = ROOT / "pc" / "src" / "bootloader_upgrade_tool" / "__main__.py"
    text = gui_entry.read_text(encoding="utf-8")

    assert "from .gui import run" in text
    assert "from .cli" not in text


def test_console_script_is_declared_without_changing_product_packaging_shape() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["scripts"]["bootloader-cli"] == "bootloader_upgrade_tool.cli.main:main"
