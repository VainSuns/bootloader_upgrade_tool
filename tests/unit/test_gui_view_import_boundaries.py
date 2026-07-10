from pathlib import Path


GUI_ROOT = Path(__file__).resolve().parents[2] / "pc" / "src" / "bootloader_upgrade_tool" / "gui"
VIEW_FILES = (
    GUI_ROOT / "app.py",
    GUI_ROOT / "main_window.py",
    GUI_ROOT / "console_splitter.py",
    GUI_ROOT / "navigation.py",
    GUI_ROOT / "styles.py",
    GUI_ROOT / "pages" / "advanced_page.py",
    GUI_ROOT / "pages" / "logs_page.py",
    GUI_ROOT / "pages" / "memory_page.py",
    GUI_ROOT / "pages" / "placeholder_page.py",
    GUI_ROOT / "pages" / "program_page.py",
    GUI_ROOT / "pages" / "settings_page.py",
    GUI_ROOT / "widgets" / "card.py",
    GUI_ROOT / "widgets" / "page_header.py",
    GUI_ROOT / "widgets" / "status_widgets.py",
    GUI_ROOT / "widgets" / "form_rows.py",
    GUI_ROOT / "widgets" / "input_controls.py",
    GUI_ROOT / "widgets" / "navigation_panel.py",
    GUI_ROOT / "widgets" / "console_widget.py",
    *sorted((GUI_ROOT / "widgets" / "ribbon").glob("*.py")),
)
FORBIDDEN_IMPORT_FRAGMENTS = (
    "bootloader_upgrade_tool.operations",
    "bootloader_upgrade_tool.images",
    "bootloader_upgrade_tool.session",
    "bootloader_upgrade_tool.transport",
    "bootloader_upgrade_tool.protocol",
    "bootloader_upgrade_tool.targets",
    "from ..operations",
    "from ..images",
    "from ..session",
    "from ..transport",
    "from ..protocol",
    "from ..targets",
    "import serial",
    "from serial",
    "subprocess",
    "cpu1_upgrade",
    "program_controller",
)


def test_view_modules_do_not_import_backend_runtime_layers() -> None:
    for path in VIEW_FILES:
        source = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IMPORT_FRAGMENTS:
            assert forbidden not in source, f"{path} imports forbidden fragment {forbidden!r}"
