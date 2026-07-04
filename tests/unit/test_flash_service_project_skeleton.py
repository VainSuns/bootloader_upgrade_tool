from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_flash_service_project_uses_map_owned_addresses() -> None:
    assert not (ROOT / "dsp/flash_service_lib/include/boot_flash_service_image_layout.h").exists()
    projectspec = (ROOT / "dsp/flash_service_lib/cpu01/flash_service_lib_cpu01.projectspec").read_text()
    assert "boot_flash_service_image_layout.h" not in projectspec
    assert "-I${C2000WARE_ROOT}/driverlib/f2837xD/driverlib" in projectspec


def test_flash_service_project_has_no_binary_artifacts() -> None:
    forbidden = {".out", ".map", ".obj", ".lib", ".hex", ".txt"}
    files = ROOT.joinpath("dsp/flash_service_lib/cpu01").rglob("*")
    assert not [path for path in files if path.is_file() and path.suffix.lower() in forbidden]
