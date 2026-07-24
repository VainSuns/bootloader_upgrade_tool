from __future__ import annotations

from dataclasses import asdict

import pytest

from bootloader_upgrade_tool.gui.advanced_flash_operation_models import (
    AdvancedFlashEraseScope,
    EraseAdvancedFlashRequest,
    ProgramAdvancedFlashRequest,
    VerifyAdvancedFlashRequest,
)
from bootloader_upgrade_tool.gui.advanced_metadata_models import (
    WriteAdvancedAppConfirmedRequest,
    WriteAdvancedBootAttemptRequest,
    WriteAdvancedImageValidRequest,
)
from bootloader_upgrade_tool.gui.advanced_ram_models import (
    CheckAdvancedRamCrcRequest,
    LoadAdvancedRamImageRequest,
    RunAdvancedRamImageRequest,
)
from bootloader_upgrade_tool.gui.runtime_v2_models import ConnectionGeneration
from bootloader_upgrade_tool.gui.runtime_models import TaskFinalStatus
from bootloader_upgrade_tool.gui.status_models import (
    DeviceInfoRequest,
    LastErrorRequest,
    MetadataRefreshRequest,
    ProtocolInfoRequest,
)
from bootloader_upgrade_tool.operations import OperationResult
from tests.unit import test_gui_batch14_status as status_support
from tests.unit import test_gui_runtime_backend_flash_operations as flash_support
from tests.unit import test_gui_runtime_backend_metadata_operations as metadata_support
from tests.unit import test_gui_runtime_backend_ram as ram_support


class RecordingExecutor:
    def __init__(self, session, generation, order=None):
        self.session = session
        self.generation = generation
        self.is_valid = True
        self.calls = []
        self.depth = 0
        self.order = order

    def execute_foreground(self, generation, action):
        assert self.depth == 0
        self.calls.append(generation)
        if self.order is not None:
            self.order.append("lease")
        self.depth += 1
        try:
            return action(self.session)
        finally:
            self.depth -= 1

    def invalidate(self):
        self.is_valid = False


def install(backend, *, order=None):
    session = object()
    executor = RecordingExecutor(session, backend.connection_generation, order)
    backend._connection_command_executor.invalidate()
    backend._connection_command_executor = executor
    return executor, session


@pytest.mark.parametrize(
    ("request_model", "operation_name", "model"),
    (
        (MetadataRefreshRequest("connection"), "metadata_operation", status_support._metadata()),
        (DeviceInfoRequest("connection"), "device_info_operation", status_support._device_info()),
        (ProtocolInfoRequest("connection"), "protocol_info_operation", status_support._protocol_info()),
        (LastErrorRequest("connection"), "last_error_operation", status_support._last_error()),
    ),
)
def test_each_status_read_uses_one_foreground_lease_and_executor_session(
    request_model, operation_name, model
):
    sessions = []

    def operation(ctx):
        sessions.append(ctx.session)
        return status_support._ok(operation_name.removesuffix("_operation"), model)

    backend = status_support._backend(**{operation_name: operation})
    executor, session = install(backend)

    result = backend.execute("status", request_model, None, None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert executor.calls == [backend.connection_generation]
    assert sessions == [session]


@pytest.mark.parametrize(
    ("request_type", "operation_name"),
    (
        (LoadAdvancedRamImageRequest, "load_ram_operation"),
        (CheckAdvancedRamCrcRequest, "check_ram_crc_operation"),
        (RunAdvancedRamImageRequest, "run_ram_operation"),
    ),
)
def test_each_ram_operation_uses_one_foreground_lease_and_executor_session(
    tmp_path, request_type, operation_name
):
    sessions = []

    def operation(ctx, request):
        sessions.append(ctx.session)
        summary = (
            {"total_words": request.image.total_words, "image_crc32": request.image.image_crc32}
            if request_type is CheckAdvancedRamCrcRequest
            else {}
        )
        return OperationResult(True, "ram", ctx.target.name, "RAM", summary)

    backend, path, _ = ram_support.connected_backend(tmp_path, **{operation_name: operation})
    executor, session = install(backend)
    request = ram_support.ram_request(backend, path, request_type)

    result = backend.execute("ram", request, object(), None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert executor.calls == [backend.connection_generation]
    assert sessions == [session]
    if request_type is RunAdvancedRamImageRequest:
        assert result.completion_action.name == "RELEASE_CONNECTION"


@pytest.mark.parametrize(
    "request_factory",
    (
        lambda backend: flash_support.erase(
            backend, AdvancedFlashEraseScope.REQUIRED_APP_SECTORS
        ),
        lambda backend: flash_support.flash_request(backend, ProgramAdvancedFlashRequest),
        lambda backend: flash_support.flash_request(backend, VerifyAdvancedFlashRequest),
    ),
)
def test_each_flash_operation_and_required_readback_use_one_lease(
    tmp_path, request_factory
):
    operation_sessions = []
    readback_sessions = []

    def operation(ctx, _request):
        operation_sessions.append(ctx.session)
        return OperationResult(True, "flash", ctx.target.name, "FLASH", {})

    def readback(ctx):
        readback_sessions.append(ctx.session)
        return OperationResult(
            True,
            "get_metadata_summary",
            ctx.target.name,
            "GET_METADATA_SUMMARY",
            asdict(metadata_support._metadata()),
        )

    backend, *_ = flash_support.populated_backend(
        tmp_path,
        [],
        erase_flash_image_area_operation=operation,
        program_flash_operation=operation,
        verify_flash_operation=operation,
        metadata_operation=readback,
    )
    executor, session = install(backend)
    request = request_factory(backend)

    result = backend.execute("flash", request, object(), None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert executor.calls == [backend.connection_generation]
    assert operation_sessions == [session]
    assert readback_sessions == ([] if isinstance(request, VerifyAdvancedFlashRequest) else [session])


@pytest.mark.parametrize(
    "request_type",
    (
        WriteAdvancedImageValidRequest,
        WriteAdvancedBootAttemptRequest,
        WriteAdvancedAppConfirmedRequest,
    ),
)
def test_each_metadata_append_and_readback_use_one_lease(tmp_path, request_type):
    sessions = []

    def append(ctx, _request):
        sessions.append(("append", ctx.session))
        return OperationResult(
            True,
            "append",
            ctx.target.name,
            "METADATA_APPEND",
            {"written": True, "already_exists": False, "reason": None},
        )

    def readback(ctx):
        sessions.append(("readback", ctx.session))
        return OperationResult(
            True,
            "get_metadata_summary",
            ctx.target.name,
            "GET_METADATA_SUMMARY",
            asdict(metadata_support._metadata(attempts=2)),
        )

    backend, *_ = metadata_support._backend(
        tmp_path,
        [],
        metadata_operation=readback,
        append_image_valid_operation=append,
        append_boot_attempt_operation=append,
        append_app_confirmed_operation=append,
    )
    executor, session = install(backend)

    result = backend.execute(
        "metadata", metadata_support.metadata_request(backend, request_type), object(), None
    )

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert executor.calls == [backend.connection_generation]
    assert sessions == [("append", session), ("readback", session)]


def test_ram_and_flash_materialization_precede_foreground_lease(tmp_path, monkeypatch):
    ram_order = []
    ram_dir = tmp_path / "ram"
    ram_dir.mkdir()
    ram_backend, ram_path, _ = ram_support.connected_backend(
        ram_dir,
        load_ram_operation=lambda ctx, _request: OperationResult(
            True, "load", ctx.target.name, "RAM_LOAD", {}
        ),
    )
    original_ram = ram_backend._materialize_ram_app
    monkeypatch.setattr(
        ram_backend,
        "_materialize_ram_app",
        lambda **kwargs: ram_order.append("ram") or original_ram(**kwargs),
    )
    install(ram_backend, order=ram_order)
    ram_backend.execute(
        "ram",
        ram_support.ram_request(ram_backend, ram_path, LoadAdvancedRamImageRequest),
        None,
        None,
    )
    assert ram_order == ["ram", "lease"]

    flash_order = []
    flash_dir = tmp_path / "flash"
    flash_dir.mkdir()
    flash_backend, *_ = flash_support.populated_backend(flash_dir, [])
    original_app = flash_backend._materialize_flash_app
    original_service = flash_backend._materialize_flash_service
    monkeypatch.setattr(
        flash_backend,
        "_materialize_flash_app",
        lambda **kwargs: flash_order.append("app") or original_app(**kwargs),
    )
    monkeypatch.setattr(
        flash_backend,
        "_materialize_flash_service",
        lambda **kwargs: flash_order.append("service") or original_service(**kwargs),
    )
    install(flash_backend, order=flash_order)
    flash_backend.execute(
        "flash",
        flash_support.flash_request(flash_backend, ProgramAdvancedFlashRequest),
        None,
        None,
    )
    assert flash_order == ["app", "service", "lease"]


@pytest.mark.parametrize(
    "state", ("missing", "invalid", "generation", "connection_id", "target")
)
def test_missing_invalid_or_stale_executor_never_calls_status_operation(state):
    calls = []
    backend = status_support._backend(
        metadata_operation=lambda _ctx: calls.append(True)
    )
    executor = backend._connection_command_executor
    if state == "missing":
        backend._connection_command_executor = None
    elif state == "invalid":
        executor.invalidate()
    elif state == "generation":
        executor._generation = ConnectionGeneration(backend.connection_generation.value + 1)
    elif state == "target":
        backend._target = status_support.CPU2_PROFILE

    result = backend.execute(
        "status",
        MetadataRefreshRequest("other" if state == "connection_id" else "connection"),
        None,
        None,
    )

    assert result.error.code == "STALE_CONNECTION" and calls == []


def test_operation_exception_releases_lease_for_next_foreground_request():
    attempts = 0

    def operation(_ctx):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("boom")
        return status_support._ok("get_metadata_summary", status_support._metadata())

    backend = status_support._backend(metadata_operation=operation)
    executor = backend._connection_command_executor

    with pytest.raises(ValueError, match="boom"):
        backend.execute("first", MetadataRefreshRequest("connection"), None, None)
    result = backend.execute("second", MetadataRefreshRequest("connection"), None, None)

    assert result.status is TaskFinalStatus.SUCCEEDED
    assert executor.is_valid and attempts == 2
