from __future__ import annotations

import ast
import io
import re
import tokenize
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

# RAC-V2 sections 1.1, 2.2, and 3 plus gui/AGENTS.md define this shared-code boundary.
SHARED_RUNTIME_FILES = (
    "pc/src/bootloader_upgrade_tool/gui/advanced_flash_binding.py",
    "pc/src/bootloader_upgrade_tool/gui/advanced_flash_operation_binding.py",
    "pc/src/bootloader_upgrade_tool/gui/advanced_metadata_binding.py",
    "pc/src/bootloader_upgrade_tool/gui/advanced_ram_binding.py",
    "pc/src/bootloader_upgrade_tool/gui/advanced_read_binding.py",
    "pc/src/bootloader_upgrade_tool/gui/cpu_program_status_binding.py",
    "pc/src/bootloader_upgrade_tool/gui/flash_service_binding.py",
    "pc/src/bootloader_upgrade_tool/gui/global_settings_binding.py",
    "pc/src/bootloader_upgrade_tool/gui/memory_binding.py",
    "pc/src/bootloader_upgrade_tool/gui/program_image_binding.py",
    "pc/src/bootloader_upgrade_tool/gui/runtime_backend.py",
    "pc/src/bootloader_upgrade_tool/gui/runtime_binding.py",
    "pc/src/bootloader_upgrade_tool/gui/runtime_models.py",
    "pc/src/bootloader_upgrade_tool/gui/runtime_ports.py",
    "pc/src/bootloader_upgrade_tool/gui/runtime_v2_events.py",
    "pc/src/bootloader_upgrade_tool/gui/runtime_v2_models.py",
    "pc/src/bootloader_upgrade_tool/gui/runtime_v2_policies.py",
    "pc/src/bootloader_upgrade_tool/gui/runtime_v2_transition.py",
    "pc/src/bootloader_upgrade_tool/gui/session_gui_binding.py",
    "pc/src/bootloader_upgrade_tool/images/__init__.py",
    "pc/src/bootloader_upgrade_tool/images/flash_image.py",
    "pc/src/bootloader_upgrade_tool/images/identity.py",
    "pc/src/bootloader_upgrade_tool/images/models.py",
    "pc/src/bootloader_upgrade_tool/images/ram_image.py",
    "pc/src/bootloader_upgrade_tool/images/service_image.py",
    "pc/src/bootloader_upgrade_tool/operations/__init__.py",
    "pc/src/bootloader_upgrade_tool/operations/_flash_protocol.py",
    "pc/src/bootloader_upgrade_tool/operations/_ram_protocol.py",
    "pc/src/bootloader_upgrade_tool/operations/_service_runtime.py",
    "pc/src/bootloader_upgrade_tool/operations/context.py",
    "pc/src/bootloader_upgrade_tool/operations/discovery.py",
    "pc/src/bootloader_upgrade_tool/operations/execution_ops.py",
    "pc/src/bootloader_upgrade_tool/operations/flash_ops.py",
    "pc/src/bootloader_upgrade_tool/operations/metadata_ops.py",
    "pc/src/bootloader_upgrade_tool/operations/ram_ops.py",
    "pc/src/bootloader_upgrade_tool/operations/results.py",
    "pc/src/bootloader_upgrade_tool/operations/status_ops.py",
    "pc/src/bootloader_upgrade_tool/session/__init__.py",
    "pc/src/bootloader_upgrade_tool/session/session.py",
)

ENTRY_DOCUMENTS = (
    "README.md",
    "AGENTS.md",
    "pc/src/bootloader_upgrade_tool/gui/AGENTS.md",
    "docs/README.md",
)

FORBIDDEN_ENTRY_REFERENCES = (
    "docs/04_pc_gui_requirements.md",
    "docs/phase11_gui_mvp_requirements.md",
    "docs/phase11_gui_static_layout_skeleton.md",
    "docs/phase11_gui_visual_layout_contract.md",
    "docs/phase11_gui_guidance_cleanup_notes.md",
    "docs/ui/00_gui_design_goal.md",
    "docs/ui/01_uniflash_reference_analysis.md",
    "docs/ui/02_gui_layout_spec.md",
    "docs/ui/03_gui_style_spec.md",
    "docs/ui/04_component_spec.md",
    "docs/ui/05_qss_rules.md",
    "docs/ui/06_gui_refactor_plan.md",
    "docs/ui/07_gui_acceptance_checklist.md",
    ".agents/skills/pyside6-bootloader-gui/references/gui_refactor_workflow.md",
    ".agents/skills/pyside6-bootloader-gui/SKILL.md",
)

CPU_MARKER = re.compile(r"cpu[12]", re.IGNORECASE)
MARKDOWN_LINK = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")


@dataclass(frozen=True, order=True)
class CpuHit:
    path: str
    scope: str
    kind: str
    value: str
    count: int


# Existing violations only. Stage C owns their removal.
APPROVED_CPU_HITS = frozenset(
    {
        CpuHit("pc/src/bootloader_upgrade_tool/gui/advanced_metadata_binding.py", "AdvancedMetadataOperationBinding.__init__", "identifier", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/advanced_metadata_binding.py", "AdvancedMetadataOperationBinding.__init__", "identifier", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/advanced_ram_binding.py", "AdvancedRamBinding.__init__", "identifier", "cpu1", 2),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/advanced_ram_binding.py", "AdvancedRamBinding.__init__", "identifier", "cpu2", 2),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/advanced_ram_binding.py", "AdvancedRamBinding._apply_enabled", "identifier", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/advanced_ram_binding.py", "AdvancedRamBinding._apply_enabled", "identifier", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/cpu_program_status_binding.py", "<module>", "string", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/cpu_program_status_binding.py", "<module>", "string", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/cpu_program_status_binding.py", "CpuProgramStatusBinding.__init__", "identifier", "cpu1", 3),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/cpu_program_status_binding.py", "CpuProgramStatusBinding.__init__", "identifier", "cpu2", 2),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/cpu_program_status_binding.py", "CpuProgramStatusBinding.__init__", "string", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/cpu_program_status_binding.py", "CpuProgramStatusBinding.__init__", "string", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/flash_service_binding.py", "FlashServiceBinding._task_finished", "string", "cpu1", 2),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/memory_binding.py", "MemoryRuntimeBinding.__init__", "cpu_id_member", "RuntimeCpuId.CPU1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/memory_binding.py", "MemoryRuntimeBinding.__init__", "cpu_id_member", "RuntimeCpuId.CPU2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/memory_binding.py", "MemoryRuntimeBinding.__init__", "identifier", "cpu1", 4),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/memory_binding.py", "MemoryRuntimeBinding.__init__", "identifier", "cpu2", 3),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "ConnectionInfo.__post_init__", "cpu_name_branch", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "ConnectionInfo.__post_init__", "cpu_name_branch", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "ConnectionInfo.__post_init__", "cpu_name_comparison", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "ConnectionInfo.__post_init__", "cpu_name_comparison", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "ConnectionInfo.__post_init__", "string", "cpu1", 2),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "ConnectionInfo.__post_init__", "string", "cpu2", 2),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "RuntimeSnapshot.__post_init__", "cpu_name_branch", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "RuntimeSnapshot.__post_init__", "cpu_name_branch", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "RuntimeSnapshot.__post_init__", "cpu_name_comparison", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "RuntimeSnapshot.__post_init__", "cpu_name_comparison", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "RuntimeSnapshot.__post_init__", "string", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_models.py", "RuntimeSnapshot.__post_init__", "string", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_v2_models.py", "RuntimeCpuId", "identifier", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_v2_models.py", "RuntimeCpuId", "identifier", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_v2_models.py", "RuntimeCpuId", "string", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_v2_models.py", "RuntimeCpuId", "string", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_v2_models.py", "RuntimeCpuId.from_target_key", "string", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_v2_models.py", "RuntimeCpuId.from_target_key", "string", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_v2_models.py", "RuntimeV2Snapshot.__post_init__", "string", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/runtime_v2_models.py", "RuntimeV2Snapshot.__post_init__", "string", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/session_gui_binding.py", "SessionGuiBinding.__init__", "identifier", "cpu1", 5),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/session_gui_binding.py", "SessionGuiBinding.__init__", "identifier", "cpu2", 5),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/session_gui_binding.py", "SessionGuiBinding.__init__", "string", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/gui/session_gui_binding.py", "SessionGuiBinding.__init__", "string", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/__init__.py", "<module>", "identifier", "cpu1", 4),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/__init__.py", "<module>", "identifier", "cpu2", 4),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/__init__.py", "<module>", "string", "cpu1", 4),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/__init__.py", "<module>", "string", "cpu2", 4),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "BootCpu2ResetCpu1Request", "identifier", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "BootCpu2ResetCpu1Request", "identifier", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "BootCpu2RunCpu1Request", "identifier", "cpu1", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "BootCpu2RunCpu1Request", "identifier", "cpu2", 1),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "boot_cpu2_reset_cpu1", "identifier", "cpu1", 2),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "boot_cpu2_reset_cpu1", "identifier", "cpu2", 2),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "boot_cpu2_reset_cpu1", "string", "cpu1", 5),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "boot_cpu2_reset_cpu1", "string", "cpu2", 5),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "boot_cpu2_run_cpu1", "identifier", "cpu1", 2),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "boot_cpu2_run_cpu1", "identifier", "cpu2", 2),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "boot_cpu2_run_cpu1", "string", "cpu1", 5),
        CpuHit("pc/src/bootloader_upgrade_tool/operations/execution_ops.py", "boot_cpu2_run_cpu1", "string", "cpu2", 5),
    }
)


def _scope_spans(tree: ast.AST) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []

    def visit(node: ast.AST, parents: tuple[str, ...] = ()) -> None:
        next_parents = parents
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            name = ".".join((*parents, node.name))
            spans.append((node.lineno, node.end_lineno or node.lineno, name))
            next_parents = (*parents, node.name)
        for child in ast.iter_child_nodes(node):
            visit(child, next_parents)

    visit(tree)
    return spans


def _scope_for(line: int, spans: list[tuple[int, int, str]]) -> str:
    matches = (span for span in spans if span[0] <= line <= span[1])
    return max(matches, key=lambda span: (span[0], -span[1]), default=(0, 0, "<module>"))[2]


def _contains_cpu_marker(node: ast.AST) -> bool:
    return any(
        (isinstance(child, ast.Constant) and isinstance(child.value, str) and CPU_MARKER.search(child.value))
        or (isinstance(child, (ast.Name, ast.Attribute)) and CPU_MARKER.search(child.id if isinstance(child, ast.Name) else child.attr))
        for child in ast.walk(node)
    )


def _markers(value: str) -> set[str]:
    return {match.group().casefold() for match in CPU_MARKER.finditer(value)}


def _scan_python(path: Path, display_path: str | None = None) -> frozenset[CpuHit]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    spans = _scope_spans(tree)
    relative_path = display_path or path.as_posix()
    counts: Counter[tuple[str, str, str]] = Counter()

    cpu_member_positions: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        scope = _scope_for(getattr(node, "lineno", 0), spans)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for marker in _markers(node.value):
                counts[(scope, "string", marker)] += 1
        if (
            isinstance(node, ast.Attribute)
            and node.attr.casefold() in {"cpu1", "cpu2"}
            and isinstance(node.value, ast.Name)
            and node.value.id.casefold().endswith("cpuid")
        ):
            counts[(scope, "cpu_id_member", f"{node.value.id}.{node.attr}")] += 1
            cpu_member_positions.add((node.end_lineno or node.lineno, (node.end_col_offset or 0) - len(node.attr)))
        if isinstance(node, ast.Compare) and _contains_cpu_marker(node):
            for marker in _markers(ast.unparse(node)):
                counts[(scope, "cpu_name_comparison", marker)] += 1
        if isinstance(node, (ast.If, ast.IfExp, ast.While)) and _contains_cpu_marker(node.test):
            for marker in _markers(ast.unparse(node.test)):
                counts[(scope, "cpu_name_branch", marker)] += 1

    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        if token.type == tokenize.NAME and CPU_MARKER.search(token.string) and token.start not in cpu_member_positions:
            for marker in _markers(token.string):
                counts[(_scope_for(token.start[0], spans), "identifier", marker)] += 1

    return frozenset(CpuHit(relative_path, *key, count) for key, count in counts.items())


def _assert_allowlisted(
    hits: frozenset[CpuHit],
    approved: frozenset[CpuHit] = APPROVED_CPU_HITS,
) -> None:
    new = sorted(hits - approved)
    stale = sorted(approved - hits)
    assert not new and not stale, (
        f"new CPU specializations: {new!r}\n"
        f"stale allowlist entries: {stale!r}"
    )


def _discovered_shared_files() -> set[str]:
    gui = REPO_ROOT / "pc/src/bootloader_upgrade_tool/gui"
    files = {*gui.glob("*_binding.py"), *gui.glob("runtime_*.py")}
    for package in ("operations", "images", "session"):
        files.update((REPO_ROOT / f"pc/src/bootloader_upgrade_tool/{package}").glob("*.py"))
    return {path.relative_to(REPO_ROOT).as_posix() for path in files}


def test_shared_runtime_file_inventory_is_explicit_and_complete() -> None:
    assert len(SHARED_RUNTIME_FILES) == len(set(SHARED_RUNTIME_FILES))
    assert set(SHARED_RUNTIME_FILES) == _discovered_shared_files()


def test_shared_runtime_cpu_specializations_match_exact_allowlist() -> None:
    hits = frozenset().union(*(_scan_python(REPO_ROOT / path, path) for path in SHARED_RUNTIME_FILES))
    _assert_allowlisted(hits)


@pytest.mark.parametrize(
    "source",
    (
        'target = "cpu1"\n',
        "target = CpuId.CPU2\n",
        "def select_cpu1_flow():\n    pass\n",
        'def select(target):\n    return 1 if target == "cpu1" else 2\n',
    ),
)
def test_scanner_rejects_synthetic_cpu_specialization(tmp_path: Path, source: str) -> None:
    path = tmp_path / "synthetic.py"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(AssertionError, match=r"new CPU specializations: \[CpuHit"):
        _assert_allowlisted(
            _scan_python(path, "synthetic.py"),
            approved=frozenset(),
        )


def test_scanner_accepts_source_without_cpu_specialization(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.py"
    path.write_text("value = 1\n", encoding="utf-8")
    _assert_allowlisted(
        _scan_python(path, "synthetic.py"),
        approved=frozenset(),
    )


def test_entry_document_local_markdown_links_exist() -> None:
    missing: list[str] = []
    for document in ENTRY_DOCUMENTS:
        path = REPO_ROOT / document
        for raw_target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>").split(maxsplit=1)[0]
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            local_path = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if local_path and not (path.parent / local_path).resolve().exists():
                missing.append(f"{document}: {target}")
    assert not missing, f"broken local Markdown links: {missing!r}"


def test_entry_documents_do_not_reference_retired_gui_authorities() -> None:
    violations: list[str] = []
    for document in ENTRY_DOCUMENTS:
        text = (REPO_ROOT / document).read_text(encoding="utf-8").casefold().replace("\\", "/")
        for forbidden in FORBIDDEN_ENTRY_REFERENCES:
            if forbidden.casefold() in text or Path(forbidden).name.casefold() in text:
                violations.append(f"{document}: {forbidden}")
    assert not violations, f"retired GUI authority references: {violations!r}"
