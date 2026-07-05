from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_auto_boot_policy_symbols_and_paths_exist() -> None:
    header = (ROOT / "dsp/bootloader_user/include/boot_user_auto_boot.h").read_text()
    source = (ROOT / "dsp/bootloader_user/src/boot_user_auto_boot.c").read_text()

    for name in (
        "BOOT_USER_DECISION_STAY_NO_IMAGE",
        "BOOT_USER_DECISION_STAY_METADATA_INVALID",
        "BOOT_USER_DECISION_STAY_BAD_ENTRY",
        "BOOT_USER_DECISION_STAY_SERVICE_NOT_READY",
        "BOOT_USER_DECISION_STAY_BOOT_ATTEMPT_WRITE_FAILED",
        "BOOT_USER_DECISION_STAY_WAIT_APP_CONFIRM",
        "BOOT_USER_DECISION_RUN_FIRST_TRIAL",
        "BOOT_USER_DECISION_RUN_CONFIRMED_APP",
    ):
        assert name in header
        assert name in source

    assert "BootMetadata_ScanFlashRecords" in source
    assert "BootAlgorithm_TryAttachExistingService" in source
    assert "BOOT_CMD_METADATA_APPEND_RECORD" in source
    assert "BOOT_METADATA_RECORD_BOOT_ATTEMPT" in source
    assert "BootUser_JumpToFlashApp(summary.entry_point)" in source


def test_flash_project_enables_auto_boot_but_does_not_link_flash_lib() -> None:
    text = (ROOT / "dsp/bootloader_user/cpu01/bootloader_cpu01_flash.projectspec").read_text()
    assert "--define=BOOT_USER_AUTO_BOOT_ENABLE=1" in text
    assert "boot_user_auto_boot.c" in text
    assert "boot_user_auto_boot.h" in text
    assert "flash_service_lib" not in text
    assert "F021_API_F2837xD_FPU32.lib" not in text
