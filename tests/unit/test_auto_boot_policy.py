from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_auto_boot_policy_symbols_and_paths_exist() -> None:
    header = (ROOT / "dsp/bootloader_user/include/boot_user_auto_boot.h").read_text()
    source = (ROOT / "dsp/bootloader_user/src/boot_user_auto_boot.c").read_text()

    for name in (
        "BOOT_USER_DECISION_STAY_NO_IMAGE",
        "BOOT_USER_DECISION_STAY_METADATA_INVALID",
        "BOOT_USER_DECISION_STAY_BAD_ENTRY",
        "BOOT_USER_DECISION_STAY_FIRST_TRIAL_REQUIRES_PC_RUN",
        "BOOT_USER_DECISION_STAY_WAIT_APP_CONFIRM",
        "BOOT_USER_DECISION_RUN_CONFIRMED_APP",
    ):
        assert name in header
        assert name in source

    assert "BootUser_IsConfirmedBootable" in source
    assert "BootAlgorithm_TryAttachExistingService" not in source
    assert "BOOT_CMD_METADATA_APPEND_RECORD" not in source
    assert "BootUser_AppendBootAttempt" not in source


def test_flash_project_enables_auto_boot_but_does_not_link_flash_lib() -> None:
    text = (ROOT / "dsp/bootloader_user/cpu01/bootloader_cpu01_flash.projectspec").read_text()
    assert "--define=BOOT_USER_AUTO_BOOT_ENABLE=1" in text
    assert "boot_user_auto_boot.c" in text
    assert "boot_user_auto_boot.h" in text
    assert "flash_service_lib" not in text
    assert "F021_API_F2837xD_FPU32.lib" not in text


def test_startup_uses_single_connection_wait_and_no_fake_io_ready() -> None:
    main = (ROOT / "dsp/bootloader_user/cpu01/main_cpu01.c").read_text()
    io_source = (ROOT / "dsp/bootloader_user/src/boot_user_io.c").read_text()
    io_header = (ROOT / "dsp/bootloader_user/include/boot_user_io.h").read_text()

    assert main.count("BootUser_CreateIoOpsTimeout") == 1
    assert "BootMetadata_ScanFlashRecords" in main
    assert "BootUser_IsConfirmedBootable" in main
    assert "confirmed_bootable != 0U) ? 0U : 1U" in main
    assert "BootAlgorithm_Run(&algorithm)" in main
    assert "wait_forever" in io_header
    assert "BootSci_CreateIoOps(ctx, ops);\n        #endif\n        return BOOT_IO_CONNECT_TIMEOUT" not in io_source
