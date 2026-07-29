import shutil
import subprocess
from pathlib import Path
import re

import pytest

from bootloader_upgrade_tool.protocol.constants import Command, Feature, Status


ROOT = Path(__file__).resolve().parents[2]


def test_dsp_status_and_feature_constants_match_pc() -> None:
    protocol = (ROOT / "dsp/bootloader_common/include/boot_protocol.h").read_text()
    statuses = {
        name: int(value, 16)
        for name, value in re.findall(
            r"#define BOOT_STATUS_([A-Z0-9_]+)\s+\(\(uint16_t\)0x([0-9A-F]+)U\)",
            protocol,
        )
    }
    commands = {
        name: int(value, 16)
        for name, value in re.findall(
            r"#define BOOT_CMD_([A-Z0-9_]+)\s+\(\(uint16_t\)0x([0-9A-F]+)U\)",
            protocol,
        )
    }
    device_info = (ROOT / "dsp/bootloader_common/include/boot_device_info.h").read_text()
    features = {
        name: 1 << int(bit)
        for name, bit in re.findall(
            r"#define BOOT_FEATURE_([A-Z0-9_]+)\s+\(\(uint32_t\)1UL << (\d+)\)",
            device_info,
        )
    }
    assert statuses == {item.name: item.value for item in Status}
    memory_read_command = commands.pop("MEMORY_READ")
    assert memory_read_command == 0x0230
    assert memory_read_command in {item.value for item in Command}
    assert commands == {
        item.name: item.value for item in Command if item.value != memory_read_command
    }
    memory_read_feature = features.pop("MEMORY_READ")
    assert memory_read_feature == 1 << 10
    assert features == {
        item.name: item.value for item in Feature if item.name != "MEMORY_READ"
    }
    assert "BOOT_CMD_FLASH_READ" not in protocol
    assert "BOOT_READ_TARGET" not in protocol


def test_user_device_info_advertises_only_validated_phase_features() -> None:
    source = (ROOT / "dsp/bootloader_user/src/boot_user_device_info.c").read_text()

    assignment = re.search(r"info->feature_flags\s*=([^;]+);", source, re.DOTALL)
    assert assignment is not None
    flags = assignment.group(1)
    assert "BOOT_FEATURE_ERASE" in flags
    assert "BOOT_FEATURE_PROGRAM" in flags
    assert "BOOT_FEATURE_VERIFY" in flags
    assert "BOOT_FEATURE_RUN" in flags
    assert "BOOT_FEATURE_RESET" not in flags
    assert "BOOT_FEATURE_RAM_LOAD" not in flags
    assert "#if BOOT_ENABLE_MEMORY_READ\n    info->feature_flags |= BOOT_FEATURE_MEMORY_READ;\n#endif" in source
    config = (ROOT / "dsp/bootloader_user/include/boot_user_feature_config.h").read_text()
    assert "#define BOOT_ENABLE_MEMORY_READ 0U" in config


def test_dsp_phase5_core_and_service_build_and_pass_host_tests(tmp_path: Path) -> None:
    gcc = shutil.which("gcc")
    if gcc is None:
        pytest.skip("GCC is not available for the optional DSP host build")

    root = ROOT
    common_include = root / "dsp" / "bootloader_common" / "include"
    common_src = root / "dsp" / "bootloader_common" / "src"
    core_include = root / "dsp" / "bootloader_core" / "include"
    core_src = root / "dsp" / "bootloader_core" / "src"
    user_include = root / "dsp" / "bootloader_user" / "include"
    contract_include = root / "dsp" / "flash_service_contract" / "include"
    service_include = root / "dsp" / "flash_service_lib" / "include"
    service_src = root / "dsp" / "flash_service_lib" / "src"
    executable = tmp_path / "bootloader_host_tests.exe"
    flash_read_header = tmp_path / "host_flash_read.h"
    flash_read_header.write_text(
        "\n".join(
            (
                "#include <stdint.h>",
                '#include "boot_service_abi.h"',
                "uint16_t Test_ReadFlashWord(uint32_t address);",
                "uint16_t Test_ReadMemoryWord(uint32_t address);",
                "uint16_t Test_ServiceReadWord(uint32_t address);",
                "void Test_ServiceWriteWord(uint32_t address, uint16_t value);",
                "BootFlashServiceBootInitFn Test_ServiceBootInitFromAddress(uint32_t address);",
                "BootFlashServiceHandleCommandFn Test_ServiceHandleCommandFromAddress(uint32_t address);",
                "",
            )
        ),
        encoding="utf-8",
    )
    command = [
        gcc,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-include",
        str(flash_read_header),
        "-DBOOT_FLASH_READ_WORD(address)=Test_ReadFlashWord(address)",
        "-DBOOT_MEMORY_READ_WORD(address)=Test_ReadMemoryWord(address)",
        "-DBOOT_SERVICE_READ_WORD(address)=Test_ServiceReadWord(address)",
        "-DBOOT_SERVICE_WRITE_WORD(address,value)=Test_ServiceWriteWord(address,value)",
        "-DBOOT_SERVICE_BOOT_INIT_FROM_ADDRESS(address)=Test_ServiceBootInitFromAddress(address)",
        "-DBOOT_SERVICE_HANDLE_COMMAND_FROM_ADDRESS(address)=Test_ServiceHandleCommandFromAddress(address)",
        f"-I{common_include}",
        f"-I{core_include}",
        f"-I{user_include}",
        f"-I{contract_include}",
        f"-I{service_include}",
        f"-I{service_src}",
        "-DBOOT_ENABLE_RUN_RAM=1",
        "-DBOOT_ENABLE_RESET_COMMAND=1",
        "-DBOOT_ENABLE_MEMORY_READ=1",
        str(common_src / "boot_crc32.c"),
        str(common_src / "boot_metadata_scan.c"),
        str(common_src / "boot_metadata_build.c"),
        str(common_src / "boot_protocol.c"),
        str(common_src / "boot_device_info.c"),
        str(core_src / "boot_io.c"),
        str(core_src / "boot_protocol_core.c"),
        str(core_src / "boot_algorithm.c"),
        str(service_src / "boot_flash_error_map_lib.c"),
        str(service_src / "boot_flash_session_lib.c"),
        str(service_src / "boot_flash_service_lib.c"),
        str(root / "dsp" / "tests" / "test_boot_algorithm.c"),
        "-o",
        str(executable),
    ]

    subprocess.run(command, check=True, capture_output=True, text=True)
    completed = subprocess.run(
        [str(executable)], check=True, capture_output=True, text=True
    )
    assert completed.stdout.strip() == "DSP host tests passed"


def test_app_flash_service_builds_and_passes_host_tests(tmp_path: Path) -> None:
    gcc = shutil.which("gcc")
    if gcc is None:
        pytest.skip("GCC is not available for the optional DSP host build")

    app_include = ROOT / "dsp/app_flash_service/include"
    contract_include = ROOT / "dsp/flash_service_contract/include"
    common_include = ROOT / "dsp/bootloader_common/include"
    forced_include = tmp_path / "host_app_flash_service.h"
    executable = tmp_path / "app_flash_service_tests.exe"
    forced_include.write_text(
        "\n".join(
            (
                '#include "boot_service_abi.h"',
                "extern BootFlashServicePublishState g_test_publish_state;",
                "extern BootFlashServiceAppExport g_test_app_export;",
                "#define BOOT_FLASH_SERVICE_APP_GET_PUBLISH_STATE() (&g_test_publish_state)",
                "#define BOOT_FLASH_SERVICE_APP_GET_EXPORT() (&g_test_app_export)",
                "",
            )
        ),
        encoding="utf-8",
    )
    command = [
        gcc,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-include",
        str(forced_include),
        f"-I{app_include}",
        f"-I{contract_include}",
        f"-I{common_include}",
        str(ROOT / "dsp/app_flash_service/src/boot_flash_service_app.c"),
        str(ROOT / "dsp/tests/test_boot_flash_service_app.c"),
        "-o",
        str(executable),
    ]

    subprocess.run(command, check=True, capture_output=True, text=True)
    completed = subprocess.run(
        [str(executable)], check=True, capture_output=True, text=True
    )
    assert completed.stdout.strip() == "App flash service tests passed"


def test_app_flash_service_public_header_boundary() -> None:
    header = (ROOT / "dsp/app_flash_service/include/boot_flash_service_app.h").read_text()

    assert "uint16_t BootFlashServiceApp_IsAvailable(void);" in header
    assert "uint16_t BootFlashServiceApp_ConfirmCurrentImage(void);" in header
    for forbidden in (
        "boot_service_abi.h",
        "BootFlashServiceHeader",
        "BootFlashServicePublishState",
        "BootFlashServiceAppExport",
        "metadata",
        "boot_init",
        "boot_handle_command",
    ):
        assert forbidden not in header


def test_flash_service_layout_matches_linker_command_file() -> None:
    header = (ROOT / "dsp/flash_service_contract/include/boot_flash_service_layout.h").read_text()
    linker = (ROOT / "dsp/flash_service_lib/cpu01/flash_service_lib_cpu01_ramgs_lnk.cmd").read_text()
    regions = {
        "SERVICE_HEADER": "HEADER",
        "SERVICE_PUBLISH_STATE": "PUBLISH",
        "SERVICE_RUNTIME_STATE": "RUNTIME",
        "SERVICE_FRONT_RSV": "FRONT_RSV",
        "SERVICE_APP_EXPORT": "APP_EXPORT",
        "SERVICE_IMMUTABLE": "IMMUTABLE",
        "SERVICE_DATA": "DATA",
    }

    for linker_name, macro_name in regions.items():
        linker_match = re.search(
            rf"^\s*{linker_name}\s*:\s*origin\s*=\s*(0x[0-9A-F]+),\s*length\s*=\s*(0x[0-9A-F]+)",
            linker,
            re.MULTILINE,
        )
        assert linker_match is not None
        origin = re.search(
            rf"^#define BOOT_FLASH_SERVICE_{macro_name}_ORIGIN\s+(0x[0-9A-F]+)$",
            header,
            re.MULTILINE,
        )
        length = re.search(
            rf"^#define BOOT_FLASH_SERVICE_{macro_name}_LENGTH\s+(0x[0-9A-F]+)$",
            header,
            re.MULTILINE,
        )
        assert origin is not None
        assert length is not None
        assert (origin.group(1), length.group(1)) == linker_match.groups()


def test_bootloader_uses_shared_flash_service_layout() -> None:
    config = (ROOT / "dsp/bootloader_user/include/boot_user_config.h").read_text()

    assert '#include "boot_flash_service_layout.h"' in config
    assert re.search(
        r"#define BOOT_USER_FLASH_SERVICE_HEADER_ADDRESS\s*\\\s*BOOT_FLASH_SERVICE_HEADER_ORIGIN",
        config,
    )
    assert re.search(
        r"#define BOOT_USER_FLASH_SERVICE_PUBLISH_ADDRESS\s*\\\s*BOOT_FLASH_SERVICE_PUBLISH_ORIGIN",
        config,
    )
    assert "0x013000" not in config
    assert "0x013020" not in config


def test_bootloader_projectspecs_include_shared_flash_service_layout() -> None:
    expected_include = "-I${workspace_loc:/${ProjName}/contract/include}"
    expected_copy = (
        '<file action="copy" path="../../flash_service_contract/include/'
        'boot_flash_service_layout.h" targetDirectory="contract/include" />'
    )

    for name in ("bootloader_cpu01.projectspec", "bootloader_cpu01_flash.projectspec"):
        projectspec = (ROOT / "dsp/bootloader_user/cpu01" / name).read_text()
        assert projectspec.count(expected_include) == 1
        assert projectspec.count(expected_copy) == 1


def test_flash_service_core_uses_header_v2_only() -> None:
    core = (ROOT / "dsp/bootloader_core/src/boot_algorithm.c").read_text()
    header = (ROOT / "dsp/bootloader_core/include/boot_algorithm.h").read_text()
    main = (ROOT / "dsp/bootloader_user/cpu01/main_cpu01.c").read_text()

    assert "BootAlgorithm_ValidateFlashService" in core
    assert "BootAlgorithm_ValidateFlashService(&device_info, NULL)" in main
    assert "BootAlgorithm_RestoreFlashService" in core + header
    assert "BootAlgorithm_RestoreFlashService(&algorithm)" in main
    assert "BootServiceApi" not in core + header
    assert "BOOT_SERVICE_DESCRIPTOR" not in core + header
    assert "api_table" not in core + header
    assert "payload[3] = 0U" in core
    assert "payload[4] = 0U" in core
    assert "payload,\n                              12U" in core
