import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FLASH_PROJECT = ROOT / "dsp/bootloader_user/cpu01/bootloader_cpu01_flash.projectspec"
FLASH_PROD_PROJECT = ROOT / "dsp/bootloader_user/cpu01/bootloader_cpu01_flash_prod.projectspec"
RAM_PROJECT = ROOT / "dsp/bootloader_user/cpu01/bootloader_cpu01.projectspec"
FEATURE_CONFIG = ROOT / "dsp/bootloader_user/include/boot_user_feature_config.h"


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
    assert "boot_user_comm_timeout.c" in text
    assert "boot_user_comm_timeout.h" in text
    assert "boot_user_watchdog" not in text
    assert "--define=_FLASH" in text
    assert "--define=BOOT_USER_AUTO_BOOT_ENABLE=1" in text
    assert "--define=BOOT_ENABLE_MEMORY_READ=1" not in text
    assert "BOOT_ENABLE_RUN_RAM=1" not in text
    assert "BOOT_ENABLE_RESET_COMMAND=1" not in text
    assert "main_cpu01.c" in text


def test_flash_prod_bootloader_feature_contract() -> None:
    project = ET.parse(FLASH_PROD_PROJECT).getroot().find("project")
    assert project is not None
    assert project.attrib["name"] == "bootloader_cpu01_flash_prod"
    configuration = project.find("configuration")
    assert configuration is not None
    options = configuration.attrib["compilerBuildOptions"]
    assert "--define=CPU1" in options
    assert "--define=_FLASH" in options
    assert "--define=BOOT_USER_AUTO_BOOT_ENABLE=1" in options
    assert "--define=BOOT_ENABLE_MEMORY_READ=1" in options
    assert "--define=BOOT_ENABLE_RUN_RAM=1" not in options
    assert "--define=BOOT_ENABLE_RESET_COMMAND=1" not in options
    normalized = (
        FLASH_PROD_PROJECT.read_text()
        .replace("bootloader_cpu01_flash_prod", "bootloader_cpu01_flash")
        .replace("CPU1_FLASH_PROD", "CPU1_FLASH")
        .replace(" --define=BOOT_ENABLE_MEMORY_READ=1", "")
    )
    assert normalized == FLASH_PROJECT.read_text()


def test_ram_bootloader_projectspec_still_uses_ram_linker() -> None:
    text = RAM_PROJECT.read_text()
    assert "bootloader_cpu01_ramgs_lnk.cmd" in text
    assert "bootloader_cpu01_flash_lnk.cmd" not in text
    assert "--define=_FLASH" not in text
    assert "--define=BOOT_ENABLE_RUN_RAM=1" in text
    assert "--define=BOOT_ENABLE_MEMORY_READ=1" not in text
    assert "--define=BOOT_ENABLE_RESET_COMMAND=1" not in text
    assert "boot_user_comm_timeout.c" in text
    assert "boot_user_comm_timeout.h" in text
    assert "boot_user_watchdog" not in text


def test_optional_feature_defaults_remain_trimmed() -> None:
    text = FEATURE_CONFIG.read_text()
    assert "#define BOOT_ENABLE_RUN_RAM 0U" in text
    assert "#define BOOT_ENABLE_MEMORY_READ 0U" in text
    assert "#define BOOT_ENABLE_RESET_COMMAND 0U" in text
    assert "#define BOOT_ENABLE_METADATA_SUMMARY 1U" in text
