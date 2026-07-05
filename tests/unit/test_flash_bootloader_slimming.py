from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FLASH_PROJECT = ROOT / "dsp/bootloader_user/cpu01/bootloader_cpu01_flash.projectspec"
RAM_PROJECT = ROOT / "dsp/bootloader_user/cpu01/bootloader_cpu01.projectspec"
SERVICE_PROJECT = ROOT / "dsp/flash_service_lib/cpu01/flash_service_lib_cpu01.projectspec"


def test_flash_project_uses_scan_only_and_no_flash_api() -> None:
    text = FLASH_PROJECT.read_text()
    assert "boot_metadata_scan.c" in text
    assert "boot_metadata_build.c" not in text
    assert "boot_user_feature_config.h" in text
    assert "F021_API_F2837xD_FPU32.lib" not in text
    assert "Fapi_UserDefinedFunctions.c" not in text
    assert "flash_service_lib" not in text


def test_ram_project_keeps_run_ram_enabled() -> None:
    text = RAM_PROJECT.read_text()
    assert "boot_user_feature_config.h" in text
    assert "--define=BOOT_ENABLE_RUN_RAM=1" in text


def test_flash_service_lib_project_keeps_scan_and_build_metadata() -> None:
    text = SERVICE_PROJECT.read_text()
    assert "boot_metadata_scan.c" in text
    assert "boot_metadata_build.c" in text
    assert "F021_API_F2837xD_FPU32.lib" in text
    assert "Fapi_UserDefinedFunctions.c" in text
