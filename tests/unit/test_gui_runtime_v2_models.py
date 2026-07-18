from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from datetime import datetime, timezone
import inspect
from collections.abc import Mapping

import pytest

from bootloader_upgrade_tool.gui import runtime_v2_models
from bootloader_upgrade_tool.gui.runtime_models import ConnectionInfo
from bootloader_upgrade_tool.gui.runtime_v2_models import (
    ConnectionGeneration,
    DataFreshness,
    EraseScope,
    FlashImageSummary,
    ImageParseStatus,
    MemoryRuntimeState,
    RamCrcEvidence,
    RamImageSummary,
    RuntimeCpuId,
    RuntimeStateStore,
    RuntimeStateDraft,
    TargetResourceState,
    VerifyEvidence,
)


def test_runtime_draft_target_resource_is_typed_read_only_access() -> None:
    snapshot = RuntimeStateStore().snapshot()
    draft = RuntimeStateDraft(
        snapshot.connection_generation,
        snapshot.connection,
        snapshot.target_resources,
        snapshot.memory_states,
    )
    assert draft.target_resource(RuntimeCpuId.CPU1) == snapshot.target_resources[RuntimeCpuId.CPU1]
    with pytest.raises(TypeError):
        draft.target_resource("cpu1")  # type: ignore[arg-type]
from bootloader_upgrade_tool.images import (
    ImageIdentity,
    PreparedFlashImage,
    PreparedRamImage,
    RamImageIdentity,
)
from bootloader_upgrade_tool.protocol.constants import CpuId


FLASH_IDENTITY = ImageIdentity(0x82400, 8, 0x12345678, 0x82408)
RAM_IDENTITY = RamImageIdentity(0x10000, 8, 0x87654321)


def _connection(target_key: str = "cpu1") -> ConnectionInfo:
    return ConnectionInfo(
        "connection",
        "SCI / RS232",
        "COM3",
        datetime.now(timezone.utc),
        target_key,
    )


def test_runtime_cpu_id_is_strict_and_not_the_wire_cpu_id() -> None:
    assert list(RuntimeCpuId) == [RuntimeCpuId.CPU1, RuntimeCpuId.CPU2]
    assert [cpu.value for cpu in RuntimeCpuId] == ["cpu1", "cpu2"]
    assert RuntimeCpuId.from_target_key("cpu1") is RuntimeCpuId.CPU1
    assert RuntimeCpuId.from_target_key("cpu2") is RuntimeCpuId.CPU2
    with pytest.raises((TypeError, ValueError)):
        RuntimeCpuId.from_target_key(CpuId.CPU1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        RuntimeCpuId.from_target_key("CPU1")


@pytest.mark.parametrize("value", (-1, True, 1.0, "1"))
def test_connection_generation_rejects_invalid_values(value) -> None:
    with pytest.raises(ValueError):
        ConnectionGeneration(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "values",
    ((-1, 0, 0), (0, -1, 0), (0, 0, -1), (True, 0, 0), (0, False, 0), (0, 0, True)),
)
def test_ram_image_identity_is_validated_and_frozen(values) -> None:
    with pytest.raises(ValueError):
        RamImageIdentity(*values)
    with pytest.raises(FrozenInstanceError):
        RAM_IDENTITY.entry_point = 0  # type: ignore[misc]


def test_flash_summary_reuses_the_canonical_image_identity() -> None:
    summary = FlashImageSummary(FLASH_IDENTITY, 2)
    assert summary.identity is FLASH_IDENTITY
    assert runtime_v2_models.ImageIdentity is ImageIdentity
    assert sum(
        value is ImageIdentity
        for value in vars(runtime_v2_models).values()
        if inspect.isclass(value) and value.__name__ == "ImageIdentity"
    ) == 1


def test_target_resource_defaults_are_symmetric() -> None:
    store = RuntimeStateStore()
    resources = store.snapshot().target_resources
    assert set(resources) == {RuntimeCpuId.CPU1, RuntimeCpuId.CPU2}
    assert replace(resources[RuntimeCpuId.CPU1], cpu_id=RuntimeCpuId.CPU2) == resources[RuntimeCpuId.CPU2]
    assert resources[RuntimeCpuId.CPU1].erase_scope is EraseScope.REQUIRED_APP_SECTORS


def test_target_resource_parse_invariants() -> None:
    flash_summary = FlashImageSummary(FLASH_IDENTITY, 2)
    ram_summary = RamImageSummary(RAM_IDENTITY)
    ready = TargetResourceState(
        RuntimeCpuId.CPU1,
        program_image_summary=flash_summary,
        program_image_parse_status=ImageParseStatus.READY,
        ram_image_summary=ram_summary,
        ram_image_parse_status=ImageParseStatus.READY,
    )
    assert ready.program_image_summary is flash_summary and ready.ram_image_summary is ram_summary
    with pytest.raises(ValueError, match="READY"):
        TargetResourceState(RuntimeCpuId.CPU1, program_image_parse_status=ImageParseStatus.READY)
    with pytest.raises(ValueError, match="ERROR"):
        TargetResourceState(RuntimeCpuId.CPU1, program_image_parse_status=ImageParseStatus.ERROR)
    with pytest.raises(ValueError, match="EMPTY"):
        TargetResourceState(RuntimeCpuId.CPU1, program_image_parse_error="bad")
    assert TargetResourceState(
        RuntimeCpuId.CPU1,
        program_image_parse_status=ImageParseStatus.ERROR,
        program_image_parse_error="bad",
    ).program_image_parse_error == "bad"
    with pytest.raises(ValueError, match="custom_sector_mask"):
        TargetResourceState(RuntimeCpuId.CPU1, custom_sector_mask=True)  # type: ignore[arg-type]


def test_target_resources_reject_full_prepared_images() -> None:
    prepared_flash = object.__new__(PreparedFlashImage)
    prepared_ram = object.__new__(PreparedRamImage)
    with pytest.raises(TypeError, match="FlashImageSummary"):
        TargetResourceState(
            RuntimeCpuId.CPU1,
            program_image_summary=prepared_flash,  # type: ignore[arg-type]
            program_image_parse_status=ImageParseStatus.READY,
        )
    with pytest.raises(TypeError, match="RamImageSummary"):
        TargetResourceState(
            RuntimeCpuId.CPU1,
            ram_image_summary=prepared_ram,  # type: ignore[arg-type]
            ram_image_parse_status=ImageParseStatus.READY,
        )


def test_cpu_specific_replacement_changes_only_that_cpu_and_old_snapshot() -> None:
    store = RuntimeStateStore()
    before = store.snapshot()
    replacement = TargetResourceState(RuntimeCpuId.CPU1, program_image_path="cpu1.txt")
    store.replace_target_resource(RuntimeCpuId.CPU1, replacement)
    after = store.snapshot()
    assert after.target_resources[RuntimeCpuId.CPU1] is replacement
    assert after.target_resources[RuntimeCpuId.CPU2] is before.target_resources[RuntimeCpuId.CPU2]
    assert before.target_resources[RuntimeCpuId.CPU1].program_image_path == ""


def test_store_rejects_key_state_cpu_mismatch_and_wire_keys() -> None:
    store = RuntimeStateStore()
    with pytest.raises(ValueError, match="does not match"):
        store.replace_target_resource(RuntimeCpuId.CPU1, TargetResourceState(RuntimeCpuId.CPU2))
    with pytest.raises(TypeError, match="RuntimeCpuId"):
        store.replace_target_resource(CpuId.CPU1, TargetResourceState(RuntimeCpuId.CPU1))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="does not match"):
        store.replace_memory_state(RuntimeCpuId.CPU1, MemoryRuntimeState(RuntimeCpuId.CPU2))


def test_memory_state_validates_words_and_freshness() -> None:
    fresh = MemoryRuntimeState(RuntimeCpuId.CPU1, DataFreshness.FRESH, 0x1000, [0, 0xFFFF])
    assert fresh.words == (0, 0xFFFF)
    with pytest.raises(ValueError, match="base address"):
        MemoryRuntimeState(RuntimeCpuId.CPU1, DataFreshness.FRESH)
    with pytest.raises(ValueError, match="EMPTY"):
        MemoryRuntimeState(RuntimeCpuId.CPU1, words=(1,))
    for word in (-1, 0x10000, True):
        with pytest.raises(ValueError, match="16-bit"):
            MemoryRuntimeState(RuntimeCpuId.CPU1, DataFreshness.STALE, words=(word,))
    assert MemoryRuntimeState(
        RuntimeCpuId.CPU1,
        DataFreshness.STALE,
        0x1000,
        (1,),
        "connection closed",
    ).words == (1,)


def test_snapshot_mappings_are_read_only_defensive_copies() -> None:
    store = RuntimeStateStore()
    snapshot = store.snapshot()
    with pytest.raises(TypeError):
        snapshot.target_resources[RuntimeCpuId.CPU1] = TargetResourceState(RuntimeCpuId.CPU1)  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.memory_states[RuntimeCpuId.CPU1] = MemoryRuntimeState(RuntimeCpuId.CPU1)  # type: ignore[index]
    store.replace_memory_state(
        RuntimeCpuId.CPU1,
        MemoryRuntimeState(RuntimeCpuId.CPU1, DataFreshness.FRESH, 0x1000, (1,)),
    )
    assert snapshot.memory_states[RuntimeCpuId.CPU1].freshness is DataFreshness.EMPTY


def test_connection_commit_clear_and_reconnect_never_reuse_generation() -> None:
    store = RuntimeStateStore()
    assert store.snapshot().connection_generation == ConnectionGeneration(0)
    first = store.commit_connection(_connection("cpu1"))
    assert first.generation == ConnectionGeneration(1) and first.cpu_id is RuntimeCpuId.CPU1
    store.clear_connection()
    cleared = store.snapshot()
    assert cleared.connection is None and cleared.connection_generation == ConnectionGeneration(1)
    second = store.commit_connection(_connection("cpu2"))
    assert second.generation == ConnectionGeneration(2) and second.cpu_id is RuntimeCpuId.CPU2


def test_evidence_is_frozen_and_uses_full_canonical_identities() -> None:
    verify = VerifyEvidence(RuntimeCpuId.CPU1, ConnectionGeneration(1), FLASH_IDENTITY, "verify")
    ram = RamCrcEvidence(
        RuntimeCpuId.CPU1,
        ConnectionGeneration(1),
        RAM_IDENTITY,
        RAM_IDENTITY.entry_point,
        RAM_IDENTITY.image_crc32,
        "ram-crc",
    )
    assert verify.image_identity is FLASH_IDENTITY and ram.ram_image_identity is RAM_IDENTITY
    with pytest.raises(FrozenInstanceError):
        verify.operation_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="entry_point"):
        RamCrcEvidence(RuntimeCpuId.CPU1, ConnectionGeneration(1), RAM_IDENTITY, 1, RAM_IDENTITY.image_crc32, "crc")
    with pytest.raises(ValueError, match="image_crc32"):
        RamCrcEvidence(RuntimeCpuId.CPU1, ConnectionGeneration(1), RAM_IDENTITY, RAM_IDENTITY.entry_point, 1, "crc")


def _walk(value):
    yield value
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk(key)
            yield from _walk(item)
    elif isinstance(value, tuple):
        for item in value:
            yield from _walk(item)
    elif is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            yield from _walk(getattr(value, item.name))


def test_snapshot_contains_only_frozen_lightweight_data() -> None:
    store = RuntimeStateStore()
    store.replace_target_resource(
        RuntimeCpuId.CPU1,
        TargetResourceState(
            RuntimeCpuId.CPU1,
            program_image_summary=FlashImageSummary(FLASH_IDENTITY, 2),
            program_image_parse_status=ImageParseStatus.READY,
            ram_image_summary=RamImageSummary(RAM_IDENTITY),
            ram_image_parse_status=ImageParseStatus.READY,
        ),
    )
    store.replace_memory_state(
        RuntimeCpuId.CPU1,
        MemoryRuntimeState(RuntimeCpuId.CPU1, DataFreshness.FRESH, 0x1000, (1, 2)),
    )
    store.commit_connection(_connection())
    values = tuple(_walk(store.snapshot()))
    forbidden_names = {
        "FirmwareImage",
        "PreparedFlashImage",
        "PreparedRamImage",
        "PreparedServiceImage",
        "UpgradeSession",
        "BootProtocolClient",
        "SerialTransport",
        "QObject",
        "lock",
    }
    assert not any(type(value).__name__ in forbidden_names for value in values)
    assert not any(callable(value) for value in values)


def test_runtime_v2_models_have_no_pyside6_dependency() -> None:
    assert "PySide6" not in inspect.getsource(runtime_v2_models)
