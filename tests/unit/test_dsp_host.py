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
    forced_include = tmp_path / "host_app_flash_service.h"
    executable = tmp_path / "app_flash_service_tests.exe"
    forced_include.write_text(
        "\n".join(
            (
                '#include "boot_flash_service_app_contract.h"',
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
        str(ROOT / "dsp/app_flash_service/src/boot_flash_service_app.c"),
        str(ROOT / "dsp/tests/test_boot_flash_service_app.c"),
        "-o",
        str(executable),
    ]

    assert all("bootloader_common" not in argument for argument in command)
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
        "boot_flash_service_app_contract.h",
        "boot_flash_service_layout.h",
        "boot_service_abi.h",
        "boot_protocol.h",
        "boot_device_info.h",
        "BootFlashServiceHeader",
        "BootFlashServicePublishState",
        "BootFlashServiceAppExport",
        "BootFlashServiceBootInitFn",
        "BootFlashServiceHandleCommandFn",
        "metadata",
        "capabilities",
    ):
        assert forbidden not in header


def test_app_flash_service_implementation_include_boundary() -> None:
    source = (ROOT / "dsp/app_flash_service/src/boot_flash_service_app.c").read_text()

    for required in (
        '#include "boot_flash_service_app.h"',
        '#include "boot_flash_service_layout.h"',
        '#include "boot_flash_service_app_contract.h"',
    ):
        assert required in source
    for forbidden in (
        "boot_service_abi.h",
        "boot_protocol.h",
        "boot_device_info.h",
    ):
        assert forbidden not in source


def test_app_flash_service_status_aliases_match_protocol() -> None:
    app_header = (ROOT / "dsp/app_flash_service/include/boot_flash_service_app.h").read_text()
    protocol = (ROOT / "dsp/bootloader_common/include/boot_protocol.h").read_text()

    def macro_value(source: str, name: str) -> int:
        match = re.search(
            rf"#define {name}\s+\\?\s*\(\(uint16_t\)0x([0-9A-F]+)U\)",
            source,
        )
        assert match is not None
        return int(match.group(1), 16)

    assert macro_value(app_header, "BOOT_FLASH_SERVICE_APP_STATUS_OK") == macro_value(
        protocol, "BOOT_STATUS_OK"
    )
    assert macro_value(
        app_header, "BOOT_FLASH_SERVICE_APP_STATUS_UNAVAILABLE"
    ) == macro_value(protocol, "BOOT_STATUS_UNSUPPORTED_FEATURE")


def test_app_flash_service_contract_is_single_lightweight_authority() -> None:
    abi = (ROOT / "dsp/bootloader_common/include/boot_service_abi.h").read_text()
    contract = (
        ROOT / "dsp/flash_service_contract/include/boot_flash_service_app_contract.h"
    ).read_text()
    migrated = (
        "BootFlashServiceConfirmFn",
        "BootFlashServicePublishState",
        "BootFlashServiceAppExport",
        "BOOT_FLASH_SERVICE_PUBLISH_VALID",
        "BOOT_FLASH_SERVICE_PUBLISH_VALID_INVERSE",
        "BOOT_FLASH_SERVICE_PUBLISH_INVALID",
    )

    assert '#include "boot_flash_service_app_contract.h"' in abi
    for name in migrated:
        assert name not in abi
        assert name in contract
    assert re.findall(r'^#include [<"]([^>"]+)[>"]', contract, re.MULTILINE) == [
        "stdint.h"
    ]
    for forbidden in (
        "BootFlashServiceHeader",
        "BootFlashServiceBootInitFn",
        "BootFlashServiceHandleCommandFn",
        "BootProtocolFrame",
        "BootErrorDetail",
        "BootDeviceInfo",
        "capabilities",
        "metadata",
        "erase",
        "program",
        "verify",
    ):
        assert forbidden not in contract


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


def test_projectspecs_include_shared_flash_service_contract() -> None:
    expected_include = "-I${workspace_loc:/${ProjName}/contract/include}"
    app_contract_copy = (
        '<file action="copy" path="../../flash_service_contract/include/'
        'boot_flash_service_app_contract.h" targetDirectory="contract/include" />'
    )
    layout_copy = (
        '<file action="copy" path="../../flash_service_contract/include/'
        'boot_flash_service_layout.h" targetDirectory="contract/include" />'
    )

    for name in ("bootloader_cpu01.projectspec", "bootloader_cpu01_flash.projectspec"):
        projectspec = (ROOT / "dsp/bootloader_user/cpu01" / name).read_text()
        assert projectspec.count(expected_include) == 1
        assert projectspec.count(app_contract_copy) == 1
        assert projectspec.count(layout_copy) == 1

    projectspec = (
        ROOT / "dsp/flash_service_lib/cpu01/flash_service_lib_cpu01.projectspec"
    ).read_text()
    assert projectspec.count(expected_include) == 1
    assert projectspec.count(app_contract_copy) == 1


def test_cpu1_projectspecs_include_comm_timeout_without_flash_library() -> None:
    timeout_source = (
        '<file action="copy" path="../src/boot_user_comm_timeout.c" '
        'targetDirectory="user/src" />'
    )
    timeout_header = (
        '<file action="copy" path="../include/boot_user_comm_timeout.h" '
        'targetDirectory="user/include" />'
    )
    old_pie_sources = (
        "../../device_support/common/source/F2837xD_DefaultISR.c",
        "../../device_support/common/source/F2837xD_PieCtrl.c",
        "../../device_support/common/source/F2837xD_PieVect.c",
    )
    minimal_pie_sources = (
        "../src/boot_user_default_isr_minimal.c",
        "../src/boot_user_pie_ctrl_minimal.c",
        "../src/boot_user_pie_vect_minimal.c",
    )
    minimal_pie_header = "../include/boot_user_pie_minimal.h"

    for name in ("bootloader_cpu01.projectspec", "bootloader_cpu01_flash.projectspec"):
        projectspec = (ROOT / "dsp/bootloader_user/cpu01" / name).read_text()
        assert projectspec.count(timeout_source) == 1
        assert projectspec.count(timeout_header) == 1
        assert "boot_user_watchdog" not in projectspec
        for source in old_pie_sources:
            assert source not in projectspec
        for source in minimal_pie_sources:
            assert projectspec.count(source) == 1
        assert projectspec.count(minimal_pie_header) == 1
        assert "F021" not in projectspec
        assert not re.search(r'path="[^"]*flash_service_lib', projectspec)


def test_cpu1_minimal_pie_sources_are_user_owned_and_size_minimized() -> None:
    old_sources = (
        "F2837xD_DefaultISR.c",
        "F2837xD_PieCtrl.c",
        "F2837xD_PieVect.c",
    )
    for name in old_sources:
        assert not (ROOT / "dsp/device_support/common/source" / name).exists()

    user_root = ROOT / "dsp/bootloader_user"
    header = (user_root / "include/boot_user_pie_minimal.h").read_text()
    default_isr = (user_root / "src/boot_user_default_isr_minimal.c").read_text()
    pie_control = (user_root / "src/boot_user_pie_ctrl_minimal.c").read_text()
    pie_vector = (user_root / "src/boot_user_pie_vect_minimal.c").read_text()

    assert "void BootUser_InitPieCtrlMinimal(void);" in header
    assert "void BootUser_InitPieVectTableMinimal(void);" in header
    assert "__interrupt void BootUser_PieReservedIsr(void);" in header
    assert default_isr.count("__interrupt void BootUser_PieReservedIsr(void)") == 1
    assert "ESTOP0" in default_isr
    assert "for(;;)" in default_isr
    assert "void BootUser_InitPieCtrlMinimal(void)" in pie_control
    assert "void BootUser_InitPieVectTableMinimal(void)" in pie_vector
    assert "DINT;" in pie_control
    assert "PieCtrlRegs.PIECTRL.bit.ENPIE = 0U" in pie_control
    assert "EINT" not in pie_control
    for group in range(1, 13):
        assert f"PieCtrlRegs.PIEIER{group}.all = 0U" in pie_control
        assert f"PieCtrlRegs.PIEIFR{group}.all = 0U" in pie_control
    assert "PieVectTableInit" not in pie_vector
    assert "for(i = 0U; i < 221U; i++)" in pie_vector
    assert "*dest++ = default_isr" in pie_vector
    assert "dest += 3" in pie_vector
    assert "(Uint32)&BootUser_PieReservedIsr" in pie_vector
    assert "EALLOW" in pie_vector
    assert "EDIS" in pie_vector
    assert "PieCtrlRegs.PIECTRL.bit.ENPIE = 1U" in pie_vector
    for source in (default_isr, pie_control, pie_vector):
        assert "Copyright (C) 2013-2024 Texas Instruments Incorporated" in source
        assert "SPDX-License-Identifier: BSD-3-Clause" in source
        assert "Derived from TI F2837xD device-support examples" in source
        assert "this is not an\n * unmodified TI source file" in source


def test_cpu1_comm_timeout_wiring_and_jump_boundaries() -> None:
    user_root = ROOT / "dsp/bootloader_user"
    timeout_path = user_root / "src/boot_user_comm_timeout.c"
    timeout_header_path = user_root / "include/boot_user_comm_timeout.h"
    timeout = timeout_path.read_text()
    timeout_header = timeout_header_path.read_text()
    config = (user_root / "include/boot_user_config.h").read_text()
    action = (ROOT / "dsp/bootloader_user/src/boot_user_action.c").read_text()
    main = (ROOT / "dsp/bootloader_user/cpu01/main_cpu01.c").read_text()

    assert not (user_root / "src/boot_user_watchdog.c").exists()
    assert not (user_root / "include/boot_user_watchdog.h").exists()
    assert timeout_path.exists()
    assert timeout_header_path.exists()
    assert "#define BOOT_USER_CPU_SYSCLK_HZ           200000000UL" in config
    assert "#define BOOT_USER_COMM_TIMEOUT_MS         15000UL" in config
    assert "BOOT_USER_COMM_TIMEOUT_CYCLES" in timeout
    assert "1ULL" in timeout
    assert "0xFFFFFFFFULL" in timeout
    assert "CpuTimer2Regs" in timeout
    assert "CpuTimer0Regs" not in timeout
    assert "CpuTimer1Regs" not in timeout
    assert "PieVectTable.TIMER2_INT = &BootUser_CommTimeoutIsr" in timeout
    assert "IER |= M_INT14" in timeout
    assert "IER &= (uint16_t)(~M_INT14)" in timeout
    assert "TMR2CLKSRCSEL = 0U" in timeout
    assert "TMR2CLKPRESCALE = 0U" in timeout
    assert "TCR.bit.FREE = 0U" in timeout
    assert "TCR.bit.SOFT = 0U" in timeout
    assert "PieVectTable.WAKE_INT" not in timeout
    assert "PIEIER1.bit.INTx8" not in timeout
    assert re.search(r"\bM_INT1\b", timeout) is None
    assert "tick" not in timeout.lower()
    assert "Copyright (C) 2013-2024 Texas Instruments Incorporated" in timeout
    assert "SPDX-License-Identifier: BSD-3-Clause" in timeout
    assert "BOOT_USER_SYSCTRL_REGWRITE_DELAY" in timeout
    assert 'asm(" RPT #69 || NOP")' in timeout
    assert "sysctl.h" not in timeout
    assert "SysCtl_resetDevice" not in timeout
    assert "BOOT_USER_SYSCTRL_REGWRITE_DELAY" not in timeout_header

    start = timeout.split("void BootUser_CommTimeoutStart", 1)[1].split(
        "void BootUser_CommTimeoutStop", 1
    )[0]
    clock_source = start.index("TMR2CLKSRCSEL = 0U")
    source_delay = start.index("BOOT_USER_SYSCTRL_REGWRITE_DELAY", clock_source)
    clock_prescale = start.index("TMR2CLKPRESCALE = 0U", source_delay)
    clock_edis = start.index("EDIS", clock_prescale)
    prescale_delay = start.index("BOOT_USER_SYSCTRL_REGWRITE_DELAY", clock_edis)
    assert clock_source < source_delay < clock_prescale < clock_edis < prescale_delay

    reset = timeout.split("static void BootUser_ForceDeviceResetNow", 1)[1].split(
        "void BootUser_CommTimeoutStart", 1
    )[0]
    release = reset.index("ReleaseFlashPump();")
    scsr = reset.index("WdRegs.SCSR.all = 0U", release)
    wdcr_enable = reset.index("WdRegs.WDCR.all = 0x0028U", scsr)
    enable_delay = reset.index("BOOT_USER_SYSCTRL_REGWRITE_DELAY", wdcr_enable)
    wdcr_bad_key = reset.index("WdRegs.WDCR.all = 0x0000U", enable_delay)
    bad_key_delay = reset.index("BOOT_USER_SYSCTRL_REGWRITE_DELAY", wdcr_bad_key)
    assert release < scsr < wdcr_enable < enable_delay < wdcr_bad_key < bad_key_delay
    assert "WdRegs.WDKEY" not in reset

    public_functions = (
        "BootUser_CommTimeoutStart",
        "BootUser_CommTimeoutStop",
        "BootUser_CommTimeoutOnValidRequestFrame",
        "BootUser_CommTimeoutServiceGuardEnter",
        "BootUser_CommTimeoutServiceGuardExit",
    )
    for name in public_functions:
        assert name in timeout_header
    for name in (
        "BootUserCommTimeoutContext",
        "BootUser_CommTimeoutIsRunning",
        "BootUser_CommTimeoutPause",
        "BootUser_CommTimeoutResume",
        "BootUser_CommTimeoutGetRemaining",
        "BootUser_CommTimeoutSetPeriod",
    ):
        assert name not in timeout_header + timeout

    valid_frame = timeout.split(
        "void BootUser_CommTimeoutOnValidRequestFrame", 1
    )[1].split("uint16_t BootUser_CommTimeoutServiceGuardEnter", 1)[0]
    assert "BootUser_CommTimeoutReload()" in valid_frame

    guard_enter = timeout.split(
        "uint16_t BootUser_CommTimeoutServiceGuardEnter", 1
    )[1].split(
        "void BootUser_CommTimeoutServiceGuardExit", 1
    )[0]
    assert "__disable_interrupts()" in guard_enter
    assert "TCR.bit.TSS = 1U" in guard_enter
    assert "TCR.bit.TIF = 1U" in guard_enter
    assert "IFR &= (uint16_t)(~M_INT14)" in guard_enter
    assert "__restore_interrupts" not in guard_enter
    guard_exit = timeout.split(
        "void BootUser_CommTimeoutServiceGuardExit", 1
    )[1].split(
        "__interrupt void BootUser_CommTimeoutIsr", 1
    )[0]
    assert guard_exit.index("BootUser_CommTimeoutReload()") < guard_exit.index(
        "TCR.bit.TSS = 0U"
    ) < guard_exit.index("__restore_interrupts(interrupt_state)")

    assert "static __interrupt" not in timeout
    assert timeout.count("\n__interrupt void BootUser_CommTimeoutIsr(void)") == 2
    isr = timeout.rsplit("__interrupt void BootUser_CommTimeoutIsr", 1)[1]
    assert "DINT;" not in isr
    assert "BootUser_ForceDeviceResetNow();" in isr
    for forbidden in (
        "BootMetadata_ScanFlashRecords",
        "BootUser_IsConfirmedBootable",
        "BootSci",
        "BootUser_JumpToFlashApp",
        "BootUser_JumpToRamApp",
        "BOOT_CMD_",
    ):
        assert forbidden not in isr

    normal_jump = action.split("BootUser_PrepareForAppJump", 1)[1].split(
        "BootUser_JumpToFlashApp", 1
    )[0]
    assert normal_jump.index("BootSci_Flush") < normal_jump.index(
        "BootUser_CommTimeoutStop"
    ) < normal_jump.index("DINT")
    assert "BootUser_EmergencyJumpToFlashApp" not in action

    assert main.count("BootUser_IsConfirmedBootable") == 1
    assert "boot_user_watchdog.h" not in main
    assert "BootUser_Watchdog" not in main
    assert "(confirmed_bootable != 0U) ? 0U : 1U" in main
    assert "if (confirmed_bootable != 0U)" in main
    assert "BootUser_JumpToFlashApp(metadata_summary.entry_point)" in main
    assert main.count("    BootUser_InitPieCtrlMinimal();") == 1
    assert main.count("    BootUser_InitPieVectTableMinimal();") == 1
    assert "    InitPieCtrl();" not in main
    assert "    InitPieVectTable();" not in main
    assert "BootUser_CommTimeoutOnValidRequestFrame" in main
    assert "BootUser_CommTimeoutServiceGuardEnter" in main
    assert "BootUser_CommTimeoutServiceGuardExit" in main
    assert main.index("BootAlgorithm_RestoreFlashService") < main.index(
        "BootUser_CommTimeoutStart"
    ) < main.index("BootAlgorithm_Run")
    core = (ROOT / "dsp/bootloader_core/src/boot_algorithm.c").read_text()
    assert "runtime_hooks.on_valid_request_frame" in core
    sci = (user_root / "src/boot_user_io_sci.c").read_text()
    assert "BootUser_CommTimeout" not in sci


def test_cpu1_bootloader_owns_flash_pump_lifecycle() -> None:
    main = (ROOT / "dsp/bootloader_user/cpu01/main_cpu01.c").read_text()
    timeout = (
        ROOT / "dsp/bootloader_user/src/boot_user_comm_timeout.c"
    ).read_text()
    flash_port = (
        ROOT
        / "dsp/flash_service_lib/port/f28377d_cpu1/src"
        / "boot_flash_port_f28377d_cpu1.c"
    ).read_text()

    assert main.index("BootAlgorithm_Init") < main.index(
        "SeizeFlashPump();"
    ) < main.index("BootAlgorithm_RestoreFlashService")
    assert main.index("action = BootAlgorithm_Run") < main.index(
        "ReleaseFlashPump();"
    ) < main.index("BootUser_HandleAlgorithmAction")

    reset = timeout.split("static void BootUser_ForceDeviceResetNow", 1)[1].split(
        "void BootUser_CommTimeoutStart", 1
    )[0]
    assert reset.index("ReleaseFlashPump();") < reset.index("WdRegs.WDCR")

    assert "FlashPumpSemaphoreRegs" not in flash_port
    assert "IPC_PUMP_KEY" not in flash_port
    erase = flash_port.split("BootFlash_EraseBySectorMask", 1)[1].split(
        "BootFlash_Program_128Bits", 1
    )[0]
    program = flash_port.split("BootFlash_Program_128Bits", 1)[1].split(
        "BootFlash_ProgramBlock", 1
    )[0]
    for operation in (erase, program):
        ready_index = operation.index("Fapi_checkFsmForReady")
        flush_index = operation.index("Fapi_flushPipeline();", ready_index)
        status_index = operation.index("Fapi_getFsmStatus", flush_index)
        assert ready_index < flush_index < status_index


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
