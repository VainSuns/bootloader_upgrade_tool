import shutil
import subprocess
from pathlib import Path
import re

import pytest

from bootloader_upgrade_tool.protocol.constants import Command, Feature, ReadTarget, Status


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
    read_targets = {
        name: int(value, 16)
        for name, value in re.findall(
            r"#define BOOT_READ_TARGET_([A-Z0-9_]+)\s+\(\(uint16_t\)0x([0-9A-F]+)U\)",
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
    assert commands == {item.name: item.value for item in Command}
    assert read_targets == {item.name: item.value for item in ReadTarget}
    assert features == {item.name: item.value for item in Feature}


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
                "uint16_t Test_ServiceReadWord(uint32_t address);",
                "const BootServiceApi *Test_ServiceApiFromAddress(uint32_t address);",
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
        "-DBOOT_SERVICE_READ_WORD(address)=Test_ServiceReadWord(address)",
        "-DBOOT_SERVICE_API_FROM_ADDRESS(address)=Test_ServiceApiFromAddress(address)",
        f"-I{common_include}",
        f"-I{core_include}",
        f"-I{user_include}",
        f"-I{service_include}",
        f"-I{service_src}",
        "-DBOOT_ENABLE_RUN_RAM=1",
        "-DBOOT_ENABLE_RESET_COMMAND=1",
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
