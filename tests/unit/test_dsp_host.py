import shutil
import subprocess
from pathlib import Path
import re

import pytest

from bootloader_upgrade_tool.protocol.constants import Feature, Status


ROOT = Path(__file__).resolve().parents[2]


def test_dsp_status_and_feature_constants_match_pc() -> None:
    protocol = (ROOT / "dsp/bootloader_algorithm/include/boot_protocol.h").read_text()
    statuses = {
        name: int(value, 16)
        for name, value in re.findall(
            r"#define BOOT_STATUS_([A-Z0-9_]+)\s+\(\(uint16_t\)0x([0-9A-F]+)U\)",
            protocol,
        )
    }
    device_info = (ROOT / "dsp/bootloader_algorithm/include/boot_device_info.h").read_text()
    features = {
        name: 1 << int(bit)
        for name, bit in re.findall(
            r"#define BOOT_FEATURE_([A-Z0-9_]+)\s+\(\(uint32_t\)1UL << (\d+)\)",
            device_info,
        )
    }
    assert statuses == {item.name: item.value for item in Status}
    assert features == {item.name: item.value for item in Feature}


def test_dsp_phase4_core_builds_and_passes_host_tests(tmp_path: Path) -> None:
    gcc = shutil.which("gcc")
    if gcc is None:
        pytest.skip("GCC is not available for the optional DSP host build")

    root = ROOT
    include = root / "dsp" / "bootloader_algorithm" / "include"
    core = root / "dsp" / "bootloader_algorithm" / "core"
    executable = tmp_path / "bootloader_host_tests.exe"
    command = [
        gcc,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        f"-I{include}",
        str(core / "boot_io.c"),
        str(core / "boot_protocol.c"),
        str(core / "boot_device_info.c"),
        str(core / "boot_algorithm.c"),
        str(root / "dsp" / "tests" / "test_boot_algorithm.c"),
        "-o",
        str(executable),
    ]

    subprocess.run(command, check=True, capture_output=True, text=True)
    completed = subprocess.run(
        [str(executable)], check=True, capture_output=True, text=True
    )
    assert completed.stdout.strip() == "DSP host tests passed"
