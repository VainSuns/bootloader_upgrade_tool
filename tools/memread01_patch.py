from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    text = read(path)
    actual = text.count(old)
    if actual < count:
        raise RuntimeError(f"{path}: expected at least {count} occurrences, found {actual}: {old[:80]!r}")
    write(path, text.replace(old, new, count))


def regex_replace(path: str, pattern: str, replacement: str, *, count: int = 1, flags: int = 0) -> None:
    text = read(path)
    updated, actual = re.subn(pattern, replacement, text, count=count, flags=flags)
    if actual != count:
        raise RuntimeError(f"{path}: expected {count} regex replacements, found {actual}: {pattern!r}")
    write(path, updated)


# DSP protocol names and feature configuration.
replace(
    "dsp/bootloader_common/include/boot_protocol.h",
    "#define BOOT_CMD_FLASH_READ               ((uint16_t)0x0230U)",
    "#define BOOT_CMD_MEMORY_READ              ((uint16_t)0x0230U)\n"
    "#define BOOT_CMD_FLASH_READ               BOOT_CMD_MEMORY_READ",
)
regex_replace(
    "dsp/bootloader_common/include/boot_protocol.h",
    r"\n#define BOOT_READ_TARGET_METADATA.*?\n#define BOOT_READ_TARGET_RAW_FLASH.*?\n",
    "\n",
    flags=re.DOTALL,
)
replace(
    "dsp/bootloader_common/include/boot_device_info.h",
    "#define BOOT_FEATURE_UNLOCK_Z2            ((uint32_t)1UL << 9)",
    "#define BOOT_FEATURE_UNLOCK_Z2            ((uint32_t)1UL << 9)\n"
    "#define BOOT_FEATURE_MEMORY_READ          ((uint32_t)1UL << 10)",
)
replace(
    "dsp/bootloader_user/include/boot_user_feature_config.h",
    "#ifndef BOOT_ENABLE_FLASH_READ\n#define BOOT_ENABLE_FLASH_READ 1U\n#endif",
    "#ifndef BOOT_ENABLE_MEMORY_READ\n#define BOOT_ENABLE_MEMORY_READ 0U\n#endif",
)

for path in (
    "dsp/bootloader_user/src/boot_user_device_info.c",
    "dsp/bootloader_user/templates/boot_user_device_info_template.c",
):
    text = read(path)
    if '#include "boot_user_feature_config.h"' not in text:
        text = text.replace('#include "boot_protocol.h"\n', '#include "boot_protocol.h"\n#include "boot_user_feature_config.h"\n', 1)
    if "BOOT_FEATURE_MEMORY_READ" not in text:
        marker = "    info->max_payload_words = BOOT_PROTOCOL_MAX_PAYLOAD_WORDS;"
        text = text.replace(
            marker,
            "#if BOOT_ENABLE_MEMORY_READ\n"
            "    info->feature_flags |= BOOT_FEATURE_MEMORY_READ;\n"
            "#endif\n"
            + marker,
            1,
        )
    write(path, text)

# DSP handler: generic address-space read, request-buffer reuse, and full compile-time cut.
replace(
    "dsp/bootloader_core/src/boot_algorithm.c",
    "#ifndef BOOT_SERVICE_READ_WORD\n#define BOOT_SERVICE_READ_WORD(address) (*(const volatile uint16_t *)(uintptr_t)(address))\n#endif",
    "#ifndef BOOT_SERVICE_READ_WORD\n#define BOOT_SERVICE_READ_WORD(address) (*(const volatile uint16_t *)(uintptr_t)(address))\n#endif\n\n"
    "#ifndef BOOT_MEMORY_READ_WORD\n"
    "#define BOOT_MEMORY_READ_WORD(address) (*(const volatile uint16_t *)(uintptr_t)(address))\n"
    "#endif",
)
new_handler = r'''#if BOOT_ENABLE_MEMORY_READ
static void BootAlgorithm_HandleMemoryRead(BootAlgorithm *algorithm)
{
    uint16_t *response_payload = algorithm->request.payload;
    uint16_t response_capacity = algorithm->device_info.max_payload_words;
    uint16_t max_read_words;
    uint16_t word_count;
    uint16_t index;
    uint32_t address;

    if (algorithm->request.payload_words != 4U)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_PAYLOAD_LENGTH);
        return;
    }

    address = BootAlgorithm_JoinU32(algorithm->request.payload[0],
                                    algorithm->request.payload[1]);
    word_count = algorithm->request.payload[2];
    if (algorithm->request.payload[3] != 0U)
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_FLAGS);
        return;
    }
    if (response_capacity > BOOT_PROTOCOL_MAX_PAYLOAD_WORDS)
    {
        response_capacity = BOOT_PROTOCOL_MAX_PAYLOAD_WORDS;
    }
    max_read_words = (response_capacity > 3U) ? (uint16_t)(response_capacity - 3U) : 0U;
    if ((word_count == 0U) || (word_count > max_read_words))
    {
        BootAlgorithm_SendStatus(algorithm, BOOT_STATUS_BAD_WORD_COUNT);
        return;
    }

    response_payload[0] = (uint16_t)(address & 0xFFFFUL);
    response_payload[1] = (uint16_t)(address >> 16U);
    response_payload[2] = word_count;
    for (index = 0U; index < word_count; index++)
    {
        response_payload[3U + index] =
            BOOT_MEMORY_READ_WORD(address + (uint32_t)index);
    }
    BootProtocol_SendResponse(&algorithm->io,
                              &algorithm->request,
                              BOOT_PKT_RESPONSE,
                              BOOT_STATUS_OK,
                              response_payload,
                              (uint16_t)(3U + word_count));
}
#endif

'''
regex_replace(
    "dsp/bootloader_core/src/boot_algorithm.c",
    r"static void BootAlgorithm_HandleFlashRead\(BootAlgorithm \*algorithm\)\n\{.*?\n\}\n\n(?=static void BootAlgorithm_HandleGetMetadataSummary)",
    new_handler,
    flags=re.DOTALL,
)
replace(
    "dsp/bootloader_core/src/boot_algorithm.c",
    "        case BOOT_CMD_FLASH_READ:\n            BootAlgorithm_HandleFlashRead(algorithm);\n            return BOOT_ALGORITHM_ACTION_NONE;",
    "#if BOOT_ENABLE_MEMORY_READ\n"
    "        case BOOT_CMD_MEMORY_READ:\n"
    "            BootAlgorithm_HandleMemoryRead(algorithm);\n"
    "            return BOOT_ALGORITHM_ACTION_NONE;\n"
    "#endif",
)

# PC protocol constants and command profiles.
replace(
    "pc/src/bootloader_upgrade_tool/protocol/constants.py",
    "    FLASH_READ = 0x0230",
    "    MEMORY_READ = 0x0230",
)
replace(
    "pc/src/bootloader_upgrade_tool/protocol/constants.py",
    "    UNLOCK_Z2 = 1 << 9",
    "    UNLOCK_Z2 = 1 << 9\n    MEMORY_READ = 1 << 10",
)
regex_replace(
    "pc/src/bootloader_upgrade_tool/protocol/constants.py",
    r"\nclass ReadTarget\(IntEnum\):\n.*?\n\n(?=class MetadataRecordType)",
    "\n",
    flags=re.DOTALL,
)
replace(
    "pc/src/bootloader_upgrade_tool/targets/command_sets.py",
    "    verify_end: int | None = None\n    get_metadata_summary: int | None = None",
    "    verify_end: int | None = None\n    memory_read: int | None = None\n    get_metadata_summary: int | None = None",
)
replace(
    "pc/src/bootloader_upgrade_tool/targets/cpu1.py",
    "    verify_end=Command.VERIFY_END,\n    get_metadata_summary=Command.GET_METADATA_SUMMARY,",
    "    verify_end=Command.VERIFY_END,\n    memory_read=Command.MEMORY_READ,\n    get_metadata_summary=Command.GET_METADATA_SUMMARY,",
)

# Legacy synchronous client receives the new one-frame wire contract.
replace(
    "pc/src/bootloader_upgrade_tool/core/client.py",
    "from ..protocol.constants import BootSlot, Command, MetadataRecordType, PacketType, ReadTarget, Status, Target",
    "from ..protocol.constants import BootSlot, Command, MetadataRecordType, PacketType, Status, Target",
)
new_client_methods = r'''    def memory_read(
        self,
        address: int,
        word_count: int,
        *,
        timeout_ms: int | None = None,
    ) -> tuple[int, tuple[int, ...]]:
        low, high = split_u32(address)
        payload = self.transact(
            Command.MEMORY_READ,
            (low, high, word_count, 0),
            timeout_ms=timeout_ms,
        )
        if len(payload) < 3:
            raise ProtocolDecodeError("MEMORY_READ response is too short")
        response_address = join_u32(payload[0], payload[1])
        response_words = payload[2]
        data = payload[3:]
        if response_address != address:
            raise ProtocolDecodeError("MEMORY_READ response address mismatch")
        if response_words != word_count or response_words != len(data):
            raise ProtocolDecodeError("MEMORY_READ response word count mismatch")
        return response_address, data

    def flash_read(
        self,
        read_target: int,
        address: int,
        word_count: int,
        *,
        timeout_ms: int | None = None,
    ) -> tuple[int, tuple[int, ...]]:
        """Compatibility wrapper for the removed metadata-only FLASH_READ API."""
        if int(read_target) != 1:
            raise ValueError("legacy flash_read only supports the former metadata target")
        return self.memory_read(address, word_count, timeout_ms=timeout_ms)

    def flash_read_metadata(
        self, address: int, word_count: int, *, timeout_ms: int | None = None
    ) -> tuple[int, ...]:
        """Compatibility wrapper; new callers must use memory_read()."""
        _address, data = self.memory_read(address, word_count, timeout_ms=timeout_ms)
        return data

'''
regex_replace(
    "pc/src/bootloader_upgrade_tool/core/client.py",
    r"    def flash_read\(.*?\n(?=    def ram_load_begin\()",
    new_client_methods,
    flags=re.DOTALL,
)

# Public operation library.
write(
    "pc/src/bootloader_upgrade_tool/operations/memory_ops.py",
    '''"""Generic advanced MEMORY_READ operation."""\n\nfrom __future__ import annotations\n\nfrom dataclasses import dataclass\n\nfrom ..protocol.constants import Feature\nfrom ..protocol.models import join_u32, split_u32\nfrom .context import OperationContext\nfrom .results import (\n    OperationFailure,\n    ProgressEvent,\n    emit_progress,\n    failure_result,\n    ok_result,\n    transact,\n)\n\n\n@dataclass(frozen=True, slots=True)\nclass MemoryReadRequest:\n    start_address: int\n    word_count: int\n\n\ndef _validate_request(request: MemoryReadRequest) -> None:\n    if type(request.start_address) is not int or not 0 <= request.start_address <= 0xFFFFFFFF:\n        raise OperationFailure(\n            "BAD_ADDRESS",\n            "start_address must fit a 32-bit C28x word address",\n            stage="MEMORY_READ_VALIDATE",\n        )\n    if type(request.word_count) is not int or request.word_count <= 0:\n        raise OperationFailure(\n            "BAD_WORD_COUNT",\n            "word_count must be positive",\n            stage="MEMORY_READ_VALIDATE",\n        )\n    if request.start_address + request.word_count > 0x100000000:\n        raise OperationFailure(\n            "BAD_ADDRESS",\n            "requested word-address interval exceeds uint32",\n            stage="MEMORY_READ_VALIDATE",\n        )\n\n\ndef memory_read(ctx: OperationContext, request: MemoryReadRequest):\n    operation = "MEMORY_READ"\n    stage = "MEMORY_READ"\n    try:\n        _validate_request(request)\n        client = ctx.session.client\n        device_info = getattr(client, "device_info", None)\n        if device_info is None:\n            raise OperationFailure(\n                "DEVICE_INFO_REQUIRED",\n                "MEMORY_READ requires cached DeviceInfo",\n                stage="MEMORY_READ_CAPABILITY",\n            )\n        if not (int(device_info.feature_flags) & int(Feature.MEMORY_READ)):\n            raise OperationFailure(\n                "UNSUPPORTED_OPERATION",\n                "The connected target does not advertise MEMORY_READ",\n                stage="MEMORY_READ_CAPABILITY",\n            )\n        max_payload_words = int(getattr(client, "effective_max_payload_words"))\n        max_chunk_words = max_payload_words - 3\n        if max_chunk_words <= 0:\n            raise OperationFailure(\n                "BAD_PAYLOAD_CAPACITY",\n                "MEMORY_READ response payload has no data capacity",\n                stage="MEMORY_READ_CAPABILITY",\n            )\n\n        words: list[int] = []\n        frame_count = 0\n        while len(words) < request.word_count:\n            chunk_address = request.start_address + len(words)\n            chunk_words = min(max_chunk_words, request.word_count - len(words))\n            low, high = split_u32(chunk_address)\n            payload = transact(\n                ctx,\n                "memory_read",\n                (low, high, chunk_words, 0),\n                stage=stage,\n            )\n            if len(payload) < 3:\n                raise OperationFailure(\n                    "PROTOCOL_DECODE_ERROR",\n                    "MEMORY_READ response is too short",\n                    stage=stage,\n                )\n            response_address = join_u32(payload[0], payload[1])\n            response_words = int(payload[2])\n            data = tuple(int(word) for word in payload[3:])\n            if response_address != chunk_address:\n                raise OperationFailure(\n                    "RESPONSE_ADDRESS_MISMATCH",\n                    "MEMORY_READ response start address does not match the request",\n                    stage=stage,\n                    details={"expected": chunk_address, "actual": response_address},\n                )\n            if response_words != chunk_words or len(data) != chunk_words:\n                raise OperationFailure(\n                    "RESPONSE_WORD_COUNT_MISMATCH",\n                    "MEMORY_READ response word count does not match the request",\n                    stage=stage,\n                    details={\n                        "expected": chunk_words,\n                        "reported": response_words,\n                        "received": len(data),\n                    },\n                )\n            words.extend(data)\n            frame_count += 1\n            emit_progress(\n                ctx,\n                ProgressEvent(\n                    operation,\n                    ctx.target.name,\n                    stage,\n                    f"Read {len(words)} of {request.word_count} words",\n                    len(words),\n                    request.word_count,\n                    chunk_words,\n                    {"address": chunk_address},\n                ),\n            )\n\n        return ok_result(\n            ctx,\n            operation,\n            "MEMORY_READ_COMPLETE",\n            {\n                "start_address": request.start_address,\n                "word_count": request.word_count,\n                "frame_count": frame_count,\n            },\n            details={"words": tuple(words)},\n        )\n    except Exception as exc:\n        return failure_result(ctx, operation, stage, exc)\n''',
)
replace(
    "pc/src/bootloader_upgrade_tool/operations/__init__.py",
    "from .metadata_ops import (",
    "from .memory_ops import MemoryReadRequest, memory_read\nfrom .metadata_ops import (",
)
replace(
    "pc/src/bootloader_upgrade_tool/operations/__init__.py",
    '    "LoadRamImageRequest",\n',
    '    "LoadRamImageRequest",\n    "MemoryReadRequest",\n',
)
replace(
    "pc/src/bootloader_upgrade_tool/operations/__init__.py",
    '    "load_ram_image",\n',
    '    "load_ram_image",\n    "memory_read",\n',
)

# Simulator uses the same generic payload and no address-region gate.
replace(
    "pc/src/bootloader_upgrade_tool/simulator/core.py",
    "    ReadTarget,\n",
    "",
)
replace(
    "pc/src/bootloader_upgrade_tool/simulator/core.py",
    "int(Feature.ERASE | Feature.PROGRAM | Feature.VERIFY | Feature.RUN | Feature.RESET | Feature.RAM_LOAD)",
    "int(Feature.ERASE | Feature.PROGRAM | Feature.VERIFY | Feature.RUN | Feature.RESET | Feature.RAM_LOAD | Feature.MEMORY_READ)",
)
replace(
    "pc/src/bootloader_upgrade_tool/simulator/core.py",
    "        self.flash: dict[int, int] = {}\n",
    "        self.flash: dict[int, int] = {}\n        self.memory: dict[int, int] = {}\n",
)
replace(
    "pc/src/bootloader_upgrade_tool/simulator/core.py",
    "            Command.FLASH_READ: self._flash_read,",
    "            Command.MEMORY_READ: self._memory_read,",
)
new_sim_handler = r'''    def _memory_read(self, request: Frame) -> Frame:
        if len(request.payload) != 4:
            return self._fail(
                request, Status.BAD_PAYLOAD_LENGTH, ErrorOperation.FRAME, ErrorStage.PAYLOAD
            )
        address = join_u32(request.payload[0], request.payload[1])
        word_count = request.payload[2]
        if request.payload[3]:
            return self._fail(request, Status.BAD_FLAGS, ErrorOperation.FRAME, ErrorStage.PAYLOAD)
        if word_count == 0 or word_count > self.device_info.max_payload_words - 3:
            return self._fail(
                request, Status.BAD_WORD_COUNT, ErrorOperation.FRAME, ErrorStage.PAYLOAD
            )
        return self._response(
            request,
            payload=(
                request.payload[0],
                request.payload[1],
                word_count,
                *(
                    self.memory.get(
                        address + index,
                        self.ram.get(address + index, self.flash.get(address + index, 0xFFFF)),
                    )
                    for index in range(word_count)
                ),
            ),
        )

'''
regex_replace(
    "pc/src/bootloader_upgrade_tool/simulator/core.py",
    r"    def _flash_read\(.*?\n(?=    def _run\()",
    new_sim_handler,
    flags=re.DOTALL,
)

# Metadata probe compatibility path now invokes the generic command.
replace(
    "pc/src/bootloader_upgrade_tool/tools/metadata_probe.py",
    "                client.flash_read_metadata(\n                    metadata_address,\n                    raw_words,\n                    timeout_ms=timeout_ms,\n                )",
    "                client.memory_read(\n                    metadata_address,\n                    raw_words,\n                    timeout_ms=timeout_ms,\n                )[1]",
)

# Existing tests migrate to formal names/payload while retaining coverage.
path = "tests/unit/test_dsp_host.py"
text = read(path)
text = text.replace("from bootloader_upgrade_tool.protocol.constants import Command, Feature, ReadTarget, Status", "from bootloader_upgrade_tool.protocol.constants import Command, Feature, Status")
text = re.sub(r"\n    read_targets = \{.*?\n    \}\n", "\n", text, flags=re.DOTALL)
text = text.replace("    assert read_targets == {item.name: item.value for item in ReadTarget}\n", "")
text = text.replace('                "uint16_t Test_ReadFlashWord(uint32_t address);",', '                "uint16_t Test_ReadFlashWord(uint32_t address);",\n                "uint16_t Test_ReadMemoryWord(uint32_t address);",')
text = text.replace('        "-DBOOT_FLASH_READ_WORD(address)=Test_ReadFlashWord(address)",', '        "-DBOOT_FLASH_READ_WORD(address)=Test_ReadFlashWord(address)",\n        "-DBOOT_MEMORY_READ_WORD(address)=Test_ReadMemoryWord(address)",')
text = text.replace('        "-DBOOT_ENABLE_RESET_COMMAND=1",', '        "-DBOOT_ENABLE_RESET_COMMAND=1",\n        "-DBOOT_ENABLE_MEMORY_READ=1",')
text = text.replace(
    '    subprocess.run(command, check=True, capture_output=True, text=True)\n    completed = subprocess.run(\n        [str(executable)], check=True, capture_output=True, text=True\n    )\n    assert completed.stdout.strip() == "DSP host tests passed"',
    '    subprocess.run(command, check=True, capture_output=True, text=True)\n    completed = subprocess.run(\n        [str(executable)], check=True, capture_output=True, text=True\n    )\n    assert completed.stdout.strip() == "DSP host tests passed"\n\n    disabled_executable = tmp_path / "bootloader_host_tests_memory_read_disabled.exe"\n    disabled_command = [\n        item if item != "-DBOOT_ENABLE_MEMORY_READ=1" else "-DBOOT_ENABLE_MEMORY_READ=0"\n        for item in command\n    ]\n    disabled_command[disabled_command.index(str(executable))] = str(disabled_executable)\n    subprocess.run(disabled_command, check=True, capture_output=True, text=True)\n    disabled = subprocess.run(\n        [str(disabled_executable)], check=True, capture_output=True, text=True\n    )\n    assert disabled.stdout.strip() == "DSP host tests passed"',
)
text += '''\n\ndef test_memory_read_handler_is_fully_compile_time_guarded_and_reuses_request_buffer() -> None:\n    source = (ROOT / "dsp/bootloader_core/src/boot_algorithm.c").read_text()\n    handler = re.search(\n        r"#if BOOT_ENABLE_MEMORY_READ\\nstatic void BootAlgorithm_HandleMemoryRead.*?#endif",\n        source,\n        re.DOTALL,\n    )\n    assert handler is not None\n    body = handler.group(0)\n    assert "uint16_t response_payload[BOOT_PROTOCOL_MAX_PAYLOAD_WORDS]" not in body\n    assert "uint16_t *response_payload = algorithm->request.payload" in body\n    assert "BOOT_METADATA_SLOT_A_START" not in body\n    assert "BOOT_CPU1" not in body and "BOOT_CPU2" not in body\n    assert "case BOOT_CMD_MEMORY_READ" in source\n    assert "BOOT_ENABLE_FLASH_READ" not in (\n        ROOT / "dsp/bootloader_user/include/boot_user_feature_config.h"\n    ).read_text()\n'''
write(path, text)

# Add C host coverage for enabled and disabled command dispatch.
path = "dsp/tests/test_boot_algorithm.c"
text = read(path)
text = text.replace(
    "static const uint32_t g_service_api_address = 0x00010020UL;",
    "static const uint32_t g_service_api_address = 0x00010020UL;\n"
    "static uint16_t g_memory_read_calls;\n"
    "static uint32_t g_memory_read_addresses[8];",
)
text = text.replace(
    "uint16_t Test_ServiceReadWord(uint32_t address)\n{",
    "uint16_t Test_ReadMemoryWord(uint32_t address)\n"
    "{\n"
    "    assert(g_memory_read_calls < 8U);\n"
    "    g_memory_read_addresses[g_memory_read_calls++] = address;\n"
    "    return (uint16_t)((address ^ 0x55AAUL) & 0xFFFFUL);\n"
    "}\n\n"
    "uint16_t Test_ServiceReadWord(uint32_t address)\n{",
)
insert = r'''
static void Test_MemoryReadCommand(void)
{
    FakeIo fake = {0};
    BootIoOps ops = Fake_Ops(&fake);
    BootDeviceInfo info = Test_DeviceInfo();
    BootAlgorithm algorithm;
    const uint32_t address = 0x12345678UL;
    uint16_t request[4] = {
        (uint16_t)(address & 0xFFFFUL),
        (uint16_t)(address >> 16U),
        2U,
        0U
    };
    size_t offset;

    g_memory_read_calls = 0U;
    assert(BootAlgorithm_Init(&algorithm, &ops, &info) == 1U);
    AppendRequest(&fake, BOOT_CMD_MEMORY_READ, 1U, request, 4U, 0U, 0U);
    assert(BootAlgorithm_ProcessOne(&algorithm) == BOOT_ALGORITHM_ACTION_NONE);
#if BOOT_ENABLE_MEMORY_READ
    offset = AssertResponse(&fake, 0U, BOOT_CMD_MEMORY_READ, 1U,
                            BOOT_PKT_RESPONSE, BOOT_STATUS_OK, 5U);
    assert(offset == 16U);
    assert(TxWord(&fake, 10U) == request[0]);
    assert(TxWord(&fake, 11U) == request[1]);
    assert(TxWord(&fake, 12U) == 2U);
    assert(TxWord(&fake, 13U) == Test_ReadMemoryWord(address));
    assert(TxWord(&fake, 14U) == Test_ReadMemoryWord(address + 1UL));
    assert(g_memory_read_calls == 4U);
    assert(g_memory_read_addresses[0] == address);
    assert(g_memory_read_addresses[1] == address + 1UL);
#else
    offset = AssertResponse(&fake, 0U, BOOT_CMD_MEMORY_READ, 1U,
                            BOOT_PKT_ERROR_RESPONSE, BOOT_STATUS_UNKNOWN_COMMAND, 0U);
    assert(offset == 11U);
    assert(g_memory_read_calls == 0U);
#endif
}

'''
text = text.replace("int main(void)\n{", insert + "int main(void)\n{", 1)
text = text.replace("    Test_ServiceProgramVerifyValidation();\n", "    Test_ServiceProgramVerifyValidation();\n    Test_MemoryReadCommand();\n", 1)
write(path, text)

# Simulator workflow tests: replace old target-aware contract with generic reads.
path = "tests/unit/test_simulator_workflow.py"
text = read(path)
text = text.replace("Command, ReadTarget, Status, Target", "Command, Status, Target")
text = text.replace("client.flash_read_metadata", "client.memory_read")
text = text.replace("assert client.memory_read(0x082000, 16) == (0xFFFF,) * 16", "assert client.memory_read(0x082000, 16)[1] == (0xFFFF,) * 16")
text = text.replace("assert client.memory_read(0x082000, 1) == (0xFFFF,)", "assert client.memory_read(0x082000, 1)[1] == (0xFFFF,)")
text = text.replace("assert client.memory_read(0x0823FF, 1) == (0xFFFF,)", "assert client.memory_read(0x0823FF, 1)[1] == (0xFFFF,)")
text = text.replace("assert client.memory_read(0x082000, 1) == (0x1234,)", "assert client.memory_read(0x082000, 1)[1] == (0x1234,)")
# Replace the old parametrized target/range rejection block completely.
text = re.sub(
    r"@pytest\.mark\.parametrize\(\n    \(\"payload\", \"status\"\),.*?assert captured\.value\.status == status\n    client\.close\(\)\n",
    '''def test_memory_read_accepts_unclassified_addresses_and_rejects_protocol_errors() -> None:\n    core, client, _ = connected()\n    core.memory[0x12345678] = 0xABCD\n    assert client.memory_read(0x12345678, 1) == (0x12345678, (0xABCD,))\n\n    for payload, status in (\n        ((*split_u32(0x082000), 0, 0), Status.BAD_WORD_COUNT),\n        ((*split_u32(0x082000), 254, 0), Status.BAD_WORD_COUNT),\n        ((*split_u32(0x082000), 1, 1), Status.BAD_FLAGS),\n        ((*split_u32(0x082000), 1), Status.BAD_PAYLOAD_LENGTH),\n    ):\n        with pytest.raises(ProtocolStatusError) as captured:\n            client.transact(Command.MEMORY_READ, payload)\n        assert captured.value.status == status\n    client.close()\n''',
    text,
    count=1,
    flags=re.DOTALL,
)
write(path, text)

# Metadata probe fake/test names.
path = "tests/unit/test_metadata_probe.py"
text = read(path)
text = text.replace("def flash_read_metadata", "def memory_read")
text = text.replace("self.flash_read_calls", "self.memory_read_calls")
text = text.replace("flash_read_calls", "memory_read_calls")
# Fake client method returns address + tuple, matching ProtocolClient.memory_read.
text = re.sub(
    r"(def memory_read\(self, address, word_count, \*, timeout_ms=None\):\n)(\s+)self\.memory_read_calls\.append\(\(address, word_count, timeout_ms\)\)\n\s+return tuple\(range\(word_count\)\)",
    r"\1\2self.memory_read_calls.append((address, word_count, timeout_ms))\n\2return address, tuple(range(word_count))",
    text,
)
write(path, text)

# New operation-focused tests, including chunking, response validation, capability and map injection.
write(
    "tests/unit/test_memory_read_operation.py",
    '''from __future__ import annotations\n\nfrom dataclasses import replace\n\nfrom bootloader_upgrade_tool.operations import MemoryReadRequest, OperationContext, memory_read\nfrom bootloader_upgrade_tool.protocol.constants import Command, Feature\nfrom bootloader_upgrade_tool.protocol.models import DeviceInfo, split_u32\nfrom bootloader_upgrade_tool.targets import CPU1_PROFILE\n\n\nclass FakeClient:\n    def __init__(self, *, feature=True, max_payload=8):\n        info = DeviceInfo(0x377D, 1, 0, 1, 0, 1, int(Feature.MEMORY_READ) if feature else 0, max_payload, 1, 2, 1)\n        self.device_info = info\n        self.effective_max_payload_words = max_payload\n        self.calls = []\n        self.mutate = None\n\n    def transact(self, command, payload=(), *, timeout_ms=None):\n        self.calls.append((command, tuple(payload), timeout_ms))\n        address = payload[0] | payload[1] << 16\n        count = payload[2]\n        response = (*split_u32(address), count, *(address + i & 0xFFFF for i in range(count)))\n        return self.mutate(response) if self.mutate else response\n\n\nclass Session:\n    def __init__(self, client):\n        self.client = client\n\n\ndef context(client, target=CPU1_PROFILE):\n    return OperationContext(Session(client), target)\n\n\ndef test_memory_read_splits_and_joins_using_word_addresses():\n    client = FakeClient(max_payload=8)\n    events = []\n    ctx = context(client)\n    ctx.progress = events.append\n    result = memory_read(ctx, MemoryReadRequest(0x12340000, 12))\n    assert result.ok\n    assert result.summary == {"start_address": 0x12340000, "word_count": 12, "frame_count": 3}\n    assert result.details["words"] == tuple((0x12340000 + i) & 0xFFFF for i in range(12))\n    assert [call[1][2] for call in client.calls] == [5, 5, 2]\n    assert [call[1][0] | call[1][1] << 16 for call in client.calls] == [\n        0x12340000, 0x12340005, 0x1234000A\n    ]\n    assert all(call[0] == int(Command.MEMORY_READ) for call in client.calls)\n    assert [event.current_words for event in events] == [5, 10, 12]\n\n\ndef test_memory_read_checks_capability_before_transact():\n    client = FakeClient(feature=False)\n    result = memory_read(context(client), MemoryReadRequest(0, 1))\n    assert not result.ok\n    assert result.error.code == "UNSUPPORTED_OPERATION"\n    assert client.calls == []\n\n\ndef test_memory_read_rejects_response_address_and_count_mismatch():\n    client = FakeClient()\n    client.mutate = lambda response: (response[0] + 1, *response[1:])\n    result = memory_read(context(client), MemoryReadRequest(0x100, 1))\n    assert not result.ok and result.error.code == "RESPONSE_ADDRESS_MISMATCH"\n\n    client = FakeClient()\n    client.mutate = lambda response: (response[0], response[1], response[2] + 1, *response[3:])\n    result = memory_read(context(client), MemoryReadRequest(0x100, 1))\n    assert not result.ok and result.error.code == "RESPONSE_WORD_COUNT_MISMATCH"\n\n\ndef test_memory_map_is_injected_data_not_a_send_gate():\n    client = FakeClient()\n    no_map_target = replace(CPU1_PROFILE, name="Synthetic CPU2 profile", cpu_id=2, memory_map=replace(CPU1_PROFILE.memory_map, flash=None, ram=None, metadata=None))\n    result = memory_read(context(client, no_map_target), MemoryReadRequest(0xDEADBEEF, 1))\n    assert result.ok\n    assert client.calls[0][1][:2] == split_u32(0xDEADBEEF)\n\n\ndef test_memory_read_request_boundaries():\n    client = FakeClient()\n    assert not memory_read(context(client), MemoryReadRequest(0, 0)).ok\n    assert memory_read(context(client), MemoryReadRequest(0xFFFFFFFF, 1)).ok\n    assert not memory_read(context(client), MemoryReadRequest(0xFFFFFFFF, 2)).ok\n''',
)

# Documentation: formal protocol and operation-library API.
path = "docs/14_communication_protocol.md"
text = read(path)
text = text.replace("#define BOOT_CMD_FLASH_READ        0x0230", "#define BOOT_CMD_MEMORY_READ       0x0230")
text = text.replace(
    "`FLASH_READ` is a single chunk transaction, not a BEGIN/DATA/END session.\nIts request payload is `(read_target, address_low, address_high, word_count,\nflags)`. The response is `(address_low, address_high, word_count, data...)`.\nThe DSP applies target/range permissions; raw Flash access is not implied.",
    "`MEMORY_READ` is an optional advanced-debug, single-chunk transaction, not a "
    "BEGIN/DATA/END session. Addresses are TMS320F28377D C28x 16-bit word "
    "addresses. Its request payload is `(address_low, address_high, word_count, "
    "flags)` with `flags = 0`. The response is `(address_low, address_high, "
    "word_count, data...)`. The DSP checks only payload length, flags, positive "
    "word count, and response capacity; it performs no address-map, CPU, region, "
    "ownership, linker-symbol, DCSM, or peripheral checks. Each word is read once "
    "through a volatile 16-bit access. Larger reads are split and reassembled by "
    "the PC. A normal build omits the handler, command branch, and capability, so "
    "0x0230 follows the ordinary unknown-command path."
)
# Add capability note near command section if absent.
if "BOOT_FEATURE_MEMORY_READ" not in text:
    text += "\n\n## MEMORY_READ capability\n\n`GET_DEVICE_INFO.feature_flags` bit 10 is `BOOT_FEATURE_MEMORY_READ`. It is present only when `BOOT_ENABLE_MEMORY_READ=1`; normal Flash-resident builds default to `0` and do not advertise the capability. Capability reports function presence only and does not validate addresses.\n"
write(path, text)

path = "docs/phase_10_8a_pc_operation_library.md"
text = read(path)
if "## MEMORY_READ" not in text:
    text += '''\n\n## MEMORY_READ advanced operation\n\n`memory_read(OperationContext, MemoryReadRequest)` is the single generic PC operation for optional advanced-debug reads. It requires the connected target to advertise `Feature.MEMORY_READ`, uses the active target profile's `memory_read` command, splits requests to `effective_max_payload_words - 3`, validates every response address/count, and concatenates words in C28x word-address order. Target memory maps are optional injected presentation/navigation data and never block an unclassified address or travel on the wire. No CPU1/CPU2-specific read workflow exists.\n'''
write(path, text)

path = "docs/phase_10_8a_operation_library_usage_example.md"
text = read(path)
if "MemoryReadRequest" not in text:
    text += '''\n\n## Advanced generic memory read\n\n```python\nfrom bootloader_upgrade_tool.operations import MemoryReadRequest, memory_read\n\nresult = memory_read(ctx, MemoryReadRequest(start_address=0x082000, word_count=512))\nif result.ok:\n    words = result.details["words"]\n```\n\nThe address is a C28x 16-bit word address. The operation performs PC-side multi-frame splitting and does not use the target memory map as a transmission gate.\n'''
write(path, text)

for path in ("docs/27_app_slot_metadata_header_design.md",):
    text = read(path).replace("FLASH_READ", "MEMORY_READ")
    write(path, text)

# Enforce that formal new code/tests/docs no longer depend on target-tagged wire fields.
for path in (
    "pc/src/bootloader_upgrade_tool/protocol/constants.py",
    "pc/src/bootloader_upgrade_tool/simulator/core.py",
    "tests/unit/test_simulator_workflow.py",
    "tests/unit/test_dsp_host.py",
    "docs/14_communication_protocol.md",
):
    text = read(path)
    if "ReadTarget" in text or "BOOT_READ_TARGET_" in text:
        raise RuntimeError(f"legacy read target remains in {path}")

print("MEMREAD-01 patch applied")
