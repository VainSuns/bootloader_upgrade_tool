from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FLASH_PROJECT = ROOT / "dsp/bootloader_user/cpu01/bootloader_cpu01_flash.projectspec"
RAM_PROJECT = ROOT / "dsp/bootloader_user/cpu01/bootloader_cpu01.projectspec"


def test_flash_bootloader_projectspec_shape() -> None:
    text = FLASH_PROJECT.read_text()
    assert "bootloader_cpu01_flash_lnk.cmd" in text
    assert "flash_service_lib" not in text
    assert "F021_API_F2837xD_FPU32.lib" not in text
    assert "Fapi_UserDefinedFunctions.c" not in text
    assert "boot_user_app_layout.h" in text
    assert "boot_user_ram_limit.h" in text
    assert "boot_user_config.h" in text
    assert "boot_user_action.h" in text
    assert "boot_user_auto_boot.c" in text
    assert "boot_user_auto_boot.h" in text
    assert "--define=BOOT_USER_AUTO_BOOT_ENABLE=1" in text
    assert "BOOT_ENABLE_RUN_RAM=1" not in text
    assert "main_cpu01.c" in text


def test_ram_bootloader_projectspec_still_uses_ram_linker() -> None:
    text = RAM_PROJECT.read_text()
    assert "bootloader_cpu01_ramgs_lnk.cmd" in text
    assert "bootloader_cpu01_flash_lnk.cmd" not in text
