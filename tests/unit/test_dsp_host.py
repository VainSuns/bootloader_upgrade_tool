import shutil
import subprocess
from pathlib import Path

import pytest


def test_dsp_phase4_core_builds_and_passes_host_tests(tmp_path: Path) -> None:
    gcc = shutil.which("gcc")
    if gcc is None:
        pytest.skip("GCC is not available for the optional DSP host build")

    root = Path(__file__).resolve().parents[2]
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
