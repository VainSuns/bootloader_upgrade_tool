from pathlib import Path


GUI_ROOT = (
    Path(__file__).resolve().parents[2]
    / "pc"
    / "src"
    / "bootloader_upgrade_tool"
    / "gui"
)


def test_layout_preview_has_no_backend_imports() -> None:
    source = (GUI_ROOT / "layout_preview.py").read_text(encoding="utf-8")
    prohibited = (
        "bootloader_upgrade_tool.operations",
        "bootloader_upgrade_tool.session",
        "bootloader_upgrade_tool.transport",
        "bootloader_upgrade_tool.protocol",
        "bootloader_upgrade_tool.images",
        "from ..operations",
        "from ..session",
        "from ..transport",
        "from ..protocol",
        "from ..images",
    )
    for token in prohibited:
        assert token not in source


def test_preview_module_does_not_open_files_or_ports() -> None:
    source = (GUI_ROOT / "layout_preview.py").read_text(encoding="utf-8")
    prohibited_calls = ("serial.Serial(", "open(", "Path(", "socket.", "subprocess.")
    for token in prohibited_calls:
        assert token not in source
