from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GUI_ROOT = REPO_ROOT / "pc" / "src" / "bootloader_upgrade_tool" / "gui"


def test_retired_phase11_files_are_removed() -> None:
    assert not (GUI_ROOT / "styles.py").exists()
    assert not (GUI_ROOT / "pages" / "placeholder_page.py").exists()


def test_no_retired_qss_or_placeholder_symbols_remain() -> None:
    python_sources = tuple(GUI_ROOT.rglob("*.py"))
    assert python_sources
    combined = "\n".join(path.read_text(encoding="utf-8") for path in python_sources)
    assert "APP_QSS" not in combined
    assert "PlaceholderPage" not in combined
    assert "PlaceholderPageSpec" not in combined


def test_navigation_uses_page_ids_only() -> None:
    navigation_source = (GUI_ROOT / "navigation.py").read_text(encoding="utf-8")
    main_window_source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    assert "coerce_page_id" not in navigation_source
    assert "PageId | str" not in navigation_source
    assert "PageId | str" not in main_window_source
    assert "def show_page(" not in main_window_source
