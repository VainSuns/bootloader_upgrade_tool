"""Single-owner runtime backend for the Batch 12 SCI session."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import tempfile
from threading import Lock
from typing import Any
from uuid import uuid4

from ..operations import (
    AppendAppConfirmedRequest,
    AppendBootAttemptRequest,
    AppendImageValidRequest,
    CheckRamCrcRequest,
    EraseFlashImageAreaRequest,
    EraseSectorMaskRequest,
    FlashOperationContext,
    LoadRamImageRequest,
    OperationContext,
    OperationCompletion,
    OperationResult,
    ProgramFlashImageRequest,
    RunRamImageRequest,
    TargetDiscoveryOutcome,
    VerifyFlashImageRequest,
    append_app_confirmed,
    append_boot_attempt,
    append_image_valid,
    check_ram_crc,
    discover_connected_target,
    erase_flash_image_area,
    erase_sector_mask,
    get_device_info,
    get_last_error,
    get_metadata_summary,
    get_protocol_info,
    load_ram_image,
    operation_result_to_dict,
    program_flash_image,
    run_ram_image,
    verify_flash_image,
)
from ..firmware.hex2000 import (
    Hex2000ConfigurationError,
    Hex2000Error,
    Hex2000NotFoundError,
    Sci8ParseError,
    locate_hex2000,
)
from ..firmware.flash_layout import image_sector_mask
from ..images import (
    PreparedFlashImage,
    PreparedRamImage,
    PreparedServiceImage,
    prepare_flash_app_image,
    prepare_ram_app_image,
    prepare_service_image,
)
from ..protocol.boot_protocol_client import ProtocolInfo
from ..protocol.models import DeviceInfo, ErrorDetail, MetadataSummary
from ..session import UpgradeSession, UpgradeSessionConfig
from ..targets import CPU1_PROFILE, CPU2_PROFILE
from ..targets import TargetProfile
from ..transport import (
    TransportError,
    TransportOpenResult,
    TransportOpenStatus,
    TransportTimeoutError,
)
from ..transport.serial_transport import SerialTransport, SerialTransportConfig
from .connection_models import SerialConnectRequest, SerialDisconnectRequest
from .advanced_ram_models import (
    AdvancedRamOperationSnapshot,
    CheckAdvancedRamCrcRequest,
    LoadAdvancedRamImageRequest,
    PrepareRamImageRequest,
    PreparedRamImageSummary,
    RunAdvancedRamImageRequest,
)
from .advanced_flash_models import PrepareAdvancedFlashImageRequest, PreparedAdvancedFlashImageSummary
from .advanced_flash_operation_models import (
    AdvancedFlashEraseScope,
    AdvancedFlashOperationSnapshot,
    AdvancedFlashOperationType,
    EraseAdvancedFlashRequest,
    ProgramAdvancedFlashRequest,
    VerifyAdvancedFlashRequest,
)
from .advanced_metadata_models import (
    AdvancedMetadataOperationSnapshot,
    AdvancedMetadataOperationType,
    CleanVerifyCredential,
    WriteAdvancedAppConfirmedRequest,
    WriteAdvancedBootAttemptRequest,
    WriteAdvancedImageValidRequest,
)
from .flash_service_models import PrepareFlashServiceRequest, PreparedFlashServiceSummary
from .image_preparation_models import (
    Hex2000Source,
    ImageSourceKind,
    PrepareFlashImageRequest,
    PreparedImageSummary,
    SourceFileFingerprint,
)
from .runtime_models import (
    ConnectionInfo,
    ErrorDisposition,
    GuiRuntimeError,
    GuiTaskWarning,
    ProgressMode,
    TaskExecutionResult,
    TaskCompletionAction,
    TaskFinalStatus,
    TaskProgressUpdate,
    TaskStepState,
)
from .runtime_v2_models import (
    ConnectionGeneration,
    RuntimeCpuId,
    RuntimeStateStore,
    RuntimeV2Snapshot,
    TargetResourceState,
)
from .runtime_v2_events import ConnectionClosed, ConnectionOpened, SessionChanged
from .runtime_v2_policies import DEFAULT_DOMAIN_POLICIES
from .runtime_v2_transition import DomainEventDispatcher, RuntimeTransitionResult
from .operation_task_adapter import operation_progress_to_task_update, operation_result_to_task_result
from .status_models import (
    DeviceInfoRequest,
    DeviceInfoStatusSnapshot,
    LastErrorRequest,
    LastErrorStatusSnapshot,
    LoadedImageMatch,
    MetadataRefreshRequest,
    MetadataScanState,
    MetadataStatusSnapshot,
    ProtocolInfoRequest,
    ProtocolInfoStatusSnapshot,
    StatusRequest,
)

TransportFactory = Callable[[SerialTransportConfig], Any]
SessionFactory = Callable[[UpgradeSessionConfig], Any]
DiscoveryOperation = Callable[[UpgradeSession], TargetDiscoveryOutcome]
StatusOperation = Callable[[OperationContext], OperationResult]


class _ImagePreparationFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RuntimeBackend:
    """Owns every live connection resource and never waits on concurrent entry."""

    def __init__(
        self,
        transport_factory: TransportFactory | None = None,
        session_factory: SessionFactory | None = None,
        discovery_operation: DiscoveryOperation = discover_connected_target,
        *,
        hex2000_executable_path: str | Path | None = None,
        sci8_temp_dir: str | Path | None = None,
        global_settings_error: str | None = None,
        device_info_operation: StatusOperation = get_device_info,
        protocol_info_operation: StatusOperation = get_protocol_info,
        last_error_operation: StatusOperation = get_last_error,
        metadata_operation: StatusOperation = get_metadata_summary,
        prepare_ram_operation=prepare_ram_app_image,
        load_ram_operation=load_ram_image,
        check_ram_crc_operation=check_ram_crc,
        run_ram_operation=run_ram_image,
        erase_flash_image_area_operation=erase_flash_image_area,
        erase_sector_mask_operation=erase_sector_mask,
        program_flash_operation=program_flash_image,
        verify_flash_operation=verify_flash_image,
        append_image_valid_operation=append_image_valid,
        append_boot_attempt_operation=append_boot_attempt,
        append_app_confirmed_operation=append_app_confirmed,
    ) -> None:
        self._lock = Lock()
        self._image_lock = Lock()
        self._runtime_v2_store = RuntimeStateStore()
        self._runtime_v2_dispatcher = DomainEventDispatcher(
            self._runtime_v2_store, DEFAULT_DOMAIN_POLICIES
        )
        self._transport_factory = transport_factory or SerialTransport
        self._session_factory = session_factory or UpgradeSession
        self._discovery_operation = discovery_operation
        self._session: Any | None = None
        self._transport: Any | None = None
        self._target: TargetProfile | None = None
        self._device_info: DeviceInfo | None = None
        self._connection_info: ConnectionInfo | None = None
        self._pending_close: Any | None = None
        self._hex2000_executable_path = (
            str(hex2000_executable_path).strip() if hex2000_executable_path is not None else ""
        )
        self._global_settings_error = global_settings_error
        self._sci8_temp_dir = str(sci8_temp_dir).strip() if sci8_temp_dir is not None else ""
        self._prepared_flash_image: PreparedFlashImage | None = None
        self._prepared_image_summary: PreparedImageSummary | None = None
        self._image_selection_revision: int | None = None
        self._prepared_ram_images: dict[str, tuple[PreparedRamImage, PreparedRamImageSummary]] = {}
        self._ram_selection_revisions = {"cpu1": 0, "cpu2": 0}
        self._prepared_advanced_flash_images: dict[
            str, tuple[PreparedFlashImage, PreparedAdvancedFlashImageSummary]
        ] = {}
        self._advanced_flash_selection_revisions = {"cpu1": 0, "cpu2": 0}
        self._prepared_service_image: PreparedServiceImage | None = None
        self._prepared_service_summary: PreparedFlashServiceSummary | None = None
        self._service_configuration_revision = 0
        self._configuration_revision = 0
        self._status_lock = Lock()
        self._metadata_status_snapshot: MetadataStatusSnapshot | None = None
        self._clean_verify_credential: CleanVerifyCredential | None = None
        self._device_info_operation = device_info_operation
        self._protocol_info_operation = protocol_info_operation
        self._last_error_operation = last_error_operation
        self._metadata_operation = metadata_operation
        self._prepare_ram_operation = prepare_ram_operation
        self._load_ram_operation = load_ram_operation
        self._check_ram_crc_operation = check_ram_crc_operation
        self._run_ram_operation = run_ram_operation
        self._erase_flash_image_area_operation = erase_flash_image_area_operation
        self._erase_sector_mask_operation = erase_sector_mask_operation
        self._program_flash_operation = program_flash_operation
        self._verify_flash_operation = verify_flash_operation
        self._append_image_valid_operation = append_image_valid_operation
        self._append_boot_attempt_operation = append_boot_attempt_operation
        self._append_app_confirmed_operation = append_app_confirmed_operation

    @property
    def active_session(self) -> Any | None:
        return self._session

    @property
    def active_transport(self) -> Any | None:
        return self._transport

    @property
    def active_target(self) -> TargetProfile | None:
        return self._target

    @property
    def active_device_info(self) -> DeviceInfo | None:
        return self._device_info

    @property
    def connection_info(self) -> ConnectionInfo | None:
        return self._connection_info

    @property
    def runtime_v2_snapshot(self) -> RuntimeV2Snapshot:
        return self._runtime_v2_store.snapshot()

    @property
    def target_resources(self) -> Mapping[RuntimeCpuId, TargetResourceState]:
        return self.runtime_v2_snapshot.target_resources

    @property
    def connection_generation(self) -> ConnectionGeneration:
        return self.runtime_v2_snapshot.connection_generation

    def subscribe_runtime_v2(self, listener) -> None:
        self._runtime_v2_dispatcher.subscribe(listener)

    def unsubscribe_runtime_v2(self, listener) -> None:
        self._runtime_v2_dispatcher.unsubscribe(listener)

    @property
    def pending_close(self) -> Any | None:
        return self._pending_close

    @property
    def prepared_flash_image(self) -> PreparedFlashImage | None:
        with self._image_lock:
            return self._prepared_flash_image

    @property
    def prepared_image_summary(self) -> PreparedImageSummary | None:
        with self._image_lock:
            return self._prepared_image_summary

    @property
    def prepared_image_cache(self) -> tuple[PreparedFlashImage | None, PreparedImageSummary | None]:
        with self._image_lock:
            return self._prepared_flash_image, self._prepared_image_summary

    def prepared_ram_image_cache(self, target_key: str):
        with self._image_lock:
            return self._prepared_ram_images.get(target_key)

    def prepared_advanced_flash_image_cache(self, target_key: str):
        with self._image_lock:
            cached = self._prepared_advanced_flash_images.get(target_key)
            if cached is None:
                return None
            try:
                current = self._fingerprint(Path(cached[1].source_path))
            except _ImagePreparationFailure:
                current = None
            if current != cached[1].source_fingerprint:
                self._prepared_advanced_flash_images.pop(target_key, None)
                if target_key == "cpu1":
                    self._clean_verify_credential = None
                return None
            return cached

    def advanced_flash_selection_revision(self, target_key: str) -> int:
        if target_key not in self._advanced_flash_selection_revisions:
            raise ValueError("invalid Advanced Flash target key")
        with self._image_lock:
            return self._advanced_flash_selection_revisions[target_key]

    def invalidate_prepared_advanced_flash_image(self, target_key: str, selection_revision: int) -> None:
        if target_key not in self._advanced_flash_selection_revisions:
            raise ValueError("invalid Advanced Flash target key")
        if type(selection_revision) is not int or selection_revision < 0:
            raise ValueError("selection_revision must be a non-negative integer")
        with self._image_lock:
            self._advanced_flash_selection_revisions[target_key] = selection_revision
            self._prepared_advanced_flash_images.pop(target_key, None)
            if target_key == "cpu1":
                self._clean_verify_credential = None

    @property
    def prepared_service_image_cache(self):
        with self._image_lock:
            if self._prepared_service_image is None or self._prepared_service_summary is None:
                return None
            summary = self._prepared_service_summary
            try:
                current_image = self._fingerprint(Path(summary.service_image_path))
                current_map = self._fingerprint(Path(summary.service_map_path))
            except _ImagePreparationFailure:
                current_image = current_map = None
            if current_image != summary.image_fingerprint or current_map != summary.map_fingerprint:
                self._prepared_service_image = None
                self._prepared_service_summary = None
                return None
            return self._prepared_service_image, self._prepared_service_summary

    @property
    def prepared_service_image(self) -> PreparedServiceImage | None:
        cached = self.prepared_service_image_cache
        return cached[0] if cached else None

    @property
    def prepared_service_summary(self) -> PreparedFlashServiceSummary | None:
        cached = self.prepared_service_image_cache
        return cached[1] if cached else None

    @property
    def service_configuration_revision(self) -> int:
        with self._image_lock:
            return self._service_configuration_revision

    def invalidate_prepared_service_image(self, configuration_revision: int) -> None:
        if type(configuration_revision) is not int or configuration_revision < 0:
            raise ValueError("configuration_revision must be a non-negative integer")
        with self._image_lock:
            self._service_configuration_revision = configuration_revision
            self._prepared_service_image = None
            self._prepared_service_summary = None

    def invalidate_prepared_ram_image(self, target_key: str, selection_revision: int) -> None:
        if target_key not in self._ram_selection_revisions:
            raise ValueError("invalid RAM target key")
        if type(selection_revision) is not int or selection_revision < 0:
            raise ValueError("selection_revision must be a non-negative integer")
        with self._image_lock:
            self._ram_selection_revisions[target_key] = selection_revision
            self._prepared_ram_images.pop(target_key, None)

    @property
    def metadata_status_snapshot(self) -> MetadataStatusSnapshot | None:
        with self._status_lock:
            return self._metadata_status_snapshot

    @property
    def clean_verify_credential(self) -> CleanVerifyCredential | None:
        with self._image_lock:
            return self._clean_verify_credential

    @property
    def hex2000_executable_path(self) -> str:
        return self._hex2000_executable_path

    @property
    def sci8_temp_dir(self) -> str:
        return self._sci8_temp_dir

    @property
    def configuration_revision(self) -> int:
        return self._configuration_revision

    def set_image_tool_paths(self, hex2000_executable_path: str, sci8_temp_dir: str) -> None:
        hex_path = hex2000_executable_path.strip()
        temp_dir = sci8_temp_dir.strip()
        if (hex_path, temp_dir) == (self._hex2000_executable_path, self._sci8_temp_dir):
            return
        self._hex2000_executable_path = hex_path
        self._sci8_temp_dir = temp_dir
        self._global_settings_error = None
        with self._image_lock:
            self._configuration_revision += 1
            self._prepared_advanced_flash_images.clear()
            self._prepared_service_image = None
            self._prepared_service_summary = None
            self._clean_verify_credential = None

    def apply_session_change(self) -> RuntimeTransitionResult:
        self._acquire()
        try:
            if any(
                value is not None
                for value in (
                    self._session,
                    self._transport,
                    self._connection_info,
                    self._pending_close,
                    self._runtime_v2_store.snapshot().connection,
                )
            ):
                raise RuntimeError("Session change requires a fully disconnected RuntimeBackend")
            result = self._runtime_v2_dispatcher.dispatch(SessionChanged())
            with self._image_lock:
                self._prepared_flash_image = None
                self._prepared_image_summary = None
                self._prepared_ram_images.clear()
                self._prepared_advanced_flash_images.clear()
                self._prepared_service_image = None
                self._prepared_service_summary = None
                self._clean_verify_credential = None
            self._clear_metadata_status()
            return result
        finally:
            self._lock.release()

    def invalidate_prepared_image_cache(self, selection_revision: int | None = None) -> None:
        if selection_revision is not None and (
            not isinstance(selection_revision, int)
            or isinstance(selection_revision, bool)
            or selection_revision < 0
        ):
            raise ValueError("selection_revision must be a non-negative integer")
        with self._image_lock:
            self._prepared_flash_image = None
            self._prepared_image_summary = None
            if selection_revision is not None:
                self._image_selection_revision = selection_revision

    def _acquire(self) -> None:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("RuntimeBackend concurrent entry is not allowed")

    def connect(self, task_id, request, cancellation, progress) -> TaskExecutionResult:
        self._acquire()
        try:
            return self._connect(task_id, request, cancellation, progress)
        finally:
            self._lock.release()

    def disconnect(self, task_id, request, cancellation, progress) -> TaskExecutionResult:
        self._acquire()
        try:
            return self._close(task_id, request, progress, "disconnect_sci", "Disconnect SCI / RS232")
        finally:
            self._lock.release()

    def shutdown(self, task_id, request, cancellation, progress) -> TaskExecutionResult:
        self._acquire()
        try:
            return self._close(task_id, request, progress, "shutdown", "Shutdown")
        finally:
            self._lock.release()

    def execute(self, task_id, request, cancellation, progress) -> TaskExecutionResult:
        self._acquire()
        try:
            if isinstance(request, MetadataRefreshRequest):
                return self._read_metadata_status(task_id, request, progress)
            if isinstance(request, DeviceInfoRequest):
                return self._read_device_info_status(task_id, request, progress)
            if isinstance(request, ProtocolInfoRequest):
                return self._read_protocol_info_status(task_id, request, progress)
            if isinstance(request, LastErrorRequest):
                return self._read_last_error_status(task_id, request, progress)
            if isinstance(request, PrepareRamImageRequest):
                return self._prepare_ram_image(task_id, request, progress)
            if isinstance(request, PrepareAdvancedFlashImageRequest):
                return self._prepare_advanced_flash_image(task_id, request, progress)
            if isinstance(request, PrepareFlashServiceRequest):
                return self._prepare_flash_service(task_id, request, progress)
            if isinstance(request, (LoadAdvancedRamImageRequest, CheckAdvancedRamCrcRequest, RunAdvancedRamImageRequest)):
                return self._execute_ram_operation(task_id, request, cancellation, progress)
            if isinstance(request, (EraseAdvancedFlashRequest, ProgramAdvancedFlashRequest, VerifyAdvancedFlashRequest)):
                return self._execute_advanced_flash_operation(task_id, request, cancellation, progress)
            if isinstance(request, (
                WriteAdvancedImageValidRequest,
                WriteAdvancedBootAttemptRequest,
                WriteAdvancedAppConfirmedRequest,
            )):
                return self._execute_advanced_metadata_operation(task_id, request, cancellation, progress)
            if isinstance(request, StatusRequest):
                raise NotImplementedError(f"unsupported status request: {type(request).__name__}")
            if not isinstance(request, PrepareFlashImageRequest):
                raise NotImplementedError(f"unsupported runtime request: {type(request).__name__}")
            return self._prepare_flash_image(task_id, request, progress)
        except _ImagePreparationFailure as exc:
            if isinstance(request, PrepareRamImageRequest):
                self._clear_ram_cache_for_revision(request.target_key, request.selection_revision)
            elif isinstance(request, PrepareAdvancedFlashImageRequest):
                self._clear_advanced_flash_cache_for_revision(request.target_key, request.selection_revision)
            elif isinstance(request, PrepareFlashServiceRequest):
                self._clear_service_cache_for_revision(request.configuration_revision)
            else:
                self._clear_image_cache_for_revision(request.selection_revision)
            return self._image_failure(task_id, request, exc)
        finally:
            self._lock.release()

    def _read_metadata_status(self, task_id, request: MetadataRefreshRequest, progress) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None:
            return self._stale_status_failure(task_id)
        try:
            result = self._call_status_operation(
                task_id, request, "GET_METADATA_SUMMARY", self._metadata_operation, captured, progress
            )
            if not isinstance(result, OperationResult):
                raise TypeError("status operation returned an invalid result")
            if self._status_connection(request.connection_id, captured) is None:
                return self._stale_status_failure(task_id, result)
            if not result.ok:
                self._clear_metadata_status_if_current(captured)
                return self._status_operation_failure(task_id, result)

            raw = MetadataSummary(**dict(result.summary))
            snapshot = self._metadata_snapshot(request, captured[3], result, raw)
            self._complete_status_step(task_id, request, result, progress)
            final_result = self._status_success(task_id, result, snapshot)
            normalized_snapshot = final_result.payload
            if not isinstance(normalized_snapshot, MetadataStatusSnapshot):
                raise TypeError("normalized Metadata payload is invalid")
            if self._status_connection(request.connection_id, captured) is None:
                return self._stale_status_failure(task_id, result)
            with self._status_lock:
                self._metadata_status_snapshot = normalized_snapshot
            return final_result
        except Exception:
            self._clear_metadata_status_if_current(captured)
            raise

    def _read_device_info_status(self, task_id, request: DeviceInfoRequest, progress) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None:
            return self._stale_status_failure(task_id)
        result = self._call_status_operation(
            task_id, request, "GET_DEVICE_INFO", self._device_info_operation, captured, progress
        )
        if not isinstance(result, OperationResult):
            raise TypeError("status operation returned an invalid result")
        if self._status_connection(request.connection_id, captured) is None:
            return self._stale_status_failure(task_id, result)
        if not result.ok:
            return self._status_operation_failure(task_id, result)

        info = DeviceInfo(**dict(result.summary))
        discovered = self._device_info
        if discovered is None:
            raise RuntimeError("connected target is missing discovery DeviceInfo")
        if (info.device_id, info.cpu_id) != (discovered.device_id, discovered.cpu_id):
            return self._target_mismatch_failure(task_id, result, discovered, info)
        snapshot = DeviceInfoStatusSnapshot(request.connection_id, captured[3], result, info)
        self._complete_status_step(task_id, request, result, progress)
        final_result = self._status_success(task_id, result, snapshot)
        if self._status_connection(request.connection_id, captured) is None:
            return self._stale_status_failure(task_id, result)
        self._device_info = info
        return final_result

    def _read_protocol_info_status(self, task_id, request: ProtocolInfoRequest, progress) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None:
            return self._stale_status_failure(task_id)
        result = self._call_status_operation(
            task_id, request, "GET_PROTOCOL_INFO", self._protocol_info_operation, captured, progress
        )
        if not isinstance(result, OperationResult):
            raise TypeError("status operation returned an invalid result")
        if self._status_connection(request.connection_id, captured) is None:
            return self._stale_status_failure(task_id, result)
        if not result.ok:
            return self._status_operation_failure(task_id, result)
        snapshot = ProtocolInfoStatusSnapshot(
            request.connection_id, captured[3], result, ProtocolInfo(**dict(result.summary))
        )
        self._complete_status_step(task_id, request, result, progress)
        return self._status_success(task_id, result, snapshot)

    def _read_last_error_status(self, task_id, request: LastErrorRequest, progress) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None:
            return self._stale_status_failure(task_id)
        result = self._call_status_operation(
            task_id, request, "GET_LAST_ERROR", self._last_error_operation, captured, progress
        )
        if not isinstance(result, OperationResult):
            raise TypeError("status operation returned an invalid result")
        if self._status_connection(request.connection_id, captured) is None:
            return self._stale_status_failure(task_id, result)
        if not result.ok:
            return self._status_operation_failure(task_id, result)
        snapshot = LastErrorStatusSnapshot(
            request.connection_id, captured[3], result, ErrorDetail(**dict(result.summary))
        )
        self._complete_status_step(task_id, request, result, progress)
        return self._status_success(task_id, result, snapshot)

    def _status_connection(self, connection_id: str, expected=None):
        info = self._connection_info
        if self._session is None or self._target is None or info is None or info.connection_id != connection_id:
            return None
        current = (self._session, self._target, info.connection_id, info.target_key)
        if expected is not None and (
            current[0] is not expected[0]
            or current[1] is not expected[1]
            or current[2:] != expected[2:]
        ):
            return None
        return current

    def _call_status_operation(self, task_id, request, stage, operation, captured, progress):
        step = request.create_plan(task_id).steps[0]
        self._publish(task_id, step.step_id, TaskStepState.STARTED, stage, step.title, progress)
        return operation(OperationContext(captured[0], captured[1]))

    def _complete_status_step(self, task_id, request, result, progress) -> None:
        step_id = request.create_plan(task_id).steps[0].step_id
        self._publish(task_id, step_id, TaskStepState.COMPLETED, result.stage, result.operation, progress)

    def _metadata_snapshot(self, request, target_key, result, raw) -> MetadataStatusSnapshot:
        info = self._device_info
        if info is None:
            raise RuntimeError("connected target is missing discovery DeviceInfo")
        metadata_valid = bool(raw.metadata_valid) and raw.state == int(MetadataScanState.VALID)
        image_valid = metadata_valid and all(
            (
                raw.entry_point != 0,
                raw.image_size_words != 0,
                raw.image_crc32 != 0,
                raw.target_device_id == info.device_id,
                raw.target_cpu_id == info.cpu_id,
            )
        )
        flash = self._target.memory_map.flash if self._target is not None else None
        entry_point_valid = bool(
            image_valid
            and raw.entry_point % 8 == 0
            and flash is not None
            and any(address_range.contains(raw.entry_point) for address_range in flash.app_ranges)
        )
        boot_attempt_present = image_valid and raw.boot_attempt_count > 0
        app_confirmed = image_valid and bool(raw.app_confirmed)
        confirmed_bootable = bool(
            metadata_valid and image_valid and entry_point_valid and boot_attempt_present and app_confirmed
        )
        loaded_image_match = self._loaded_image_match(target_key, raw, image_valid)
        return MetadataStatusSnapshot(
            request.connection_id,
            target_key,
            result,
            raw,
            metadata_valid,
            image_valid,
            entry_point_valid,
            boot_attempt_present,
            app_confirmed,
            confirmed_bootable,
            loaded_image_match,
            request.automatic,
        )

    def _loaded_image_match(self, target_key, raw, image_valid: bool) -> LoadedImageMatch:
        if not image_valid:
            return LoadedImageMatch.NO_VALID_TARGET_IMAGE
        with self._image_lock:
            prepared = self._prepared_image_summary
        if target_key != "cpu1" or prepared is None or prepared.target_key != "cpu1":
            return LoadedImageMatch.NO_PREPARED_IMAGE
        matches = (
            prepared.entry_point == raw.entry_point
            and prepared.image_size_words == raw.image_size_words
            and prepared.image_crc32 == raw.image_crc32
        )
        return LoadedImageMatch.MATCH if matches else LoadedImageMatch.MISMATCH

    @staticmethod
    def _status_success(task_id, result, snapshot) -> TaskExecutionResult:
        return TaskExecutionResult(
            task_id,
            TaskFinalStatus.SUCCEEDED,
            result.operation,
            result.stage,
            step_results=(result,),
            payload=snapshot,
        )

    def _status_operation_failure(self, task_id, result: OperationResult) -> TaskExecutionResult:
        error = result.error
        if error is None:
            raise RuntimeError("failed status operation did not provide error details")
        disposition = (
            ErrorDisposition.ASK_DISCONNECT
            if error.code in {"PROTOCOL_ERROR", "TARGET_MISMATCH"}
            else ErrorDisposition.SHOW_ONLY
        )
        gui_error = GuiRuntimeError(
            error.code,
            error.message,
            error.stage,
            disposition,
            task_id,
            error.recoverable,
            disposition is ErrorDisposition.ASK_DISCONNECT,
            details=error.details,
        )
        return TaskExecutionResult(
            task_id,
            TaskFinalStatus.FAILED,
            result.operation,
            result.stage,
            step_results=(result,),
            error=gui_error,
        )

    @staticmethod
    def _target_mismatch_failure(task_id, result, expected, actual) -> TaskExecutionResult:
        error = GuiRuntimeError(
            "TARGET_MISMATCH",
            "DeviceInfo changed from the connected target identity",
            result.stage,
            ErrorDisposition.ASK_DISCONNECT,
            task_id,
            True,
            True,
            details={
                "expected_device_id": expected.device_id,
                "expected_cpu_id": expected.cpu_id,
                "actual_device_id": actual.device_id,
                "actual_cpu_id": actual.cpu_id,
            },
        )
        return TaskExecutionResult(
            task_id,
            TaskFinalStatus.FAILED,
            result.operation,
            result.stage,
            step_results=(result,),
            error=error,
        )

    @staticmethod
    def _stale_status_failure(task_id, result: OperationResult | None = None) -> TaskExecutionResult:
        error = GuiRuntimeError(
            "STALE_CONNECTION",
            "The status result belongs to a connection that is no longer active",
            "status",
            ErrorDisposition.SHOW_ONLY,
            task_id,
        )
        return TaskExecutionResult(
            task_id,
            TaskFinalStatus.FAILED,
            "Status read failed",
            error.message,
            step_results=(result,) if result is not None else (),
            error=error,
        )

    def _clear_metadata_status(self) -> None:
        with self._status_lock:
            self._metadata_status_snapshot = None

    def _clear_metadata_status_if_current(self, captured) -> None:
        if self._status_connection(captured[2], captured) is not None:
            self._clear_metadata_status()

    def _connect(self, task_id, request, cancellation, progress) -> TaskExecutionResult:
        if not isinstance(request, SerialConnectRequest):
            return self._connect_settings_failure(task_id, "Invalid SCI connection request")
        try:
            self._validate_request(request)
        except ValueError as exc:
            return self._connect_settings_failure(task_id, str(exc))
        if self._session is not None or self._transport is not None:
            raise RuntimeError("connect requested while RuntimeBackend owns a session")
        if self._pending_close is not None:
            try:
                self._close_resource(self._pending_close)
            except Exception as exc:
                return self._failure(
                    task_id,
                    "SERIAL_CLOSE_FAILED",
                    str(exc),
                    stage="pre_connect_cleanup",
                    summary="Cleanup failed",
                    details={
                        "exception_type": type(exc).__name__,
                        "cleanup_pending": True,
                    },
                )
            self._pending_close = None

        session = None
        transport = None
        try:
            config = SerialTransportConfig(
                port=request.port,
                baudrate=request.baudrate,
                tx_timeout_ms=request.tx_timeout_ms,
                rx_timeout_ms=request.rx_timeout_ms,
                autobaud_timeout_ms=request.autobaud_timeout_ms,
            )
            transport = self._transport_factory(config)
            session = self._session_factory(UpgradeSessionConfig(transport))
        except Exception:
            self._cleanup_partial(session, transport)
            self._clear_active()
            raise

        self._publish(task_id, "connect_sci", TaskStepState.STARTED, "CONNECT_SCI", "Opening SCI / RS232", progress)
        try:
            open_result = self._validate_transport_open_result(session.connect(cancellation))
            if open_result.status is TransportOpenStatus.CANCELLED:
                self._clear_active()
                return TaskExecutionResult(
                    task_id,
                    TaskFinalStatus.CANCELLED,
                    "Connection cancelled",
                    f"Connection cancelled during {open_result.stage}",
                    step_results=(open_result,),
                    payload={
                        "cancellation_stage": open_result.stage,
                        "resource_released": True,
                    },
                    cancel_requested=True,
                )
            self._publish(task_id, "connect_sci", TaskStepState.COMPLETED, "CONNECT_SCI", "SCI connected", progress)
        except TransportTimeoutError as exc:
            return self._connect_failure(
                task_id, session, transport, "SCI_AUTOBAUD_TIMEOUT", str(exc), "CONNECT_SCI"
            )
        except TransportError as exc:
            return self._connect_failure(
                task_id, session, transport, "SCI_CONNECTION_FAILED", str(exc), "CONNECT_SCI"
            )
        except OSError as exc:
            return self._connect_failure(
                task_id, session, transport, "SCI_CONNECTION_FAILED", str(exc), "CONNECT_SCI"
            )
        except Exception:
            self._cleanup_partial(session, transport)
            self._clear_active()
            raise

        if cancellation is not None and cancellation.is_cancel_requested():
            return self._cancel_open_connection(
                task_id,
                session,
                transport,
                open_result,
                "BEFORE_TARGET_DISCOVERY",
                (open_result,),
            )

        try:
            self._publish(task_id, "identify_target", TaskStepState.STARTED, "IDENTIFY_TARGET", "Reading DeviceInfo", progress)
            outcome = self._discovery_operation(session)
            if not isinstance(outcome, TargetDiscoveryOutcome):
                raise RuntimeError("discovery operation returned an invalid outcome")
            evidence = (open_result, outcome.result)
            if not outcome.result.ok:
                code = outcome.result.error.code if outcome.result.error else "TARGET_DISCOVERY_FAILED"
                message = outcome.result.error.message if outcome.result.error else "Target discovery failed"
                return self._connect_failure(
                    task_id,
                    session,
                    transport,
                    code,
                    message,
                    "IDENTIFY_TARGET",
                    step_results=evidence,
                    details={"discovery_result": operation_result_to_dict(outcome.result)},
                )
            discovered = outcome.discovered_target
            if discovered is None or not isinstance(discovered.device_info, DeviceInfo):
                raise RuntimeError("successful discovery did not provide typed target data")
            connection_info = self._make_connection_info(request, discovered)
            self._publish(
                task_id,
                "identify_target",
                TaskStepState.COMPLETED,
                "IDENTIFY_TARGET",
                f"Identified {discovered.target_key.upper()}",
                progress,
            )
            if cancellation is not None and cancellation.is_cancel_requested():
                return self._cancel_open_connection(
                    task_id,
                    session,
                    transport,
                    open_result,
                    "AFTER_TARGET_DISCOVERY",
                    evidence,
                )
            result = TaskExecutionResult(
                task_id,
                TaskFinalStatus.SUCCEEDED,
                "Connected",
                f"Connected to {discovered.target_key.upper()}",
                step_results=evidence,
                payload=connection_info,
            )
            if discovered.target_key == "cpu2":
                self.invalidate_prepared_image_cache()
            self._clear_metadata_status()
            self._session = session
            self._transport = transport
            self._target = discovered.target_profile
            self._device_info = discovered.device_info
            self._connection_info = connection_info
            self._runtime_v2_dispatcher.dispatch(ConnectionOpened(connection_info))
            return result
        except Exception:
            self._cleanup_partial(session, transport)
            self._clear_active()
            raise

    @staticmethod
    def _validate_transport_open_result(value: object) -> TransportOpenResult:
        if not isinstance(value, TransportOpenResult):
            raise TypeError("UpgradeSession.connect() returned an invalid TransportOpenResult")
        if not isinstance(value.status, TransportOpenStatus):
            raise TypeError("TransportOpenResult.status must be TransportOpenStatus")
        if type(value.resource_released) is not bool:
            raise TypeError("TransportOpenResult.resource_released must be bool")
        if not isinstance(value.stage, str):
            raise TypeError("TransportOpenResult.stage must be a string")
        if not value.stage:
            raise ValueError("TransportOpenResult.stage must not be empty")
        if value.status is TransportOpenStatus.OPENED and value.resource_released:
            raise ValueError("OPENED requires resource_released=False")
        if value.status is TransportOpenStatus.CANCELLED and not value.resource_released:
            raise ValueError("CANCELLED requires resource_released=True")
        return value

    def _cancel_open_connection(
        self,
        task_id,
        session,
        transport,
        open_result: TransportOpenResult,
        cancellation_stage: str,
        step_results: tuple[object, ...],
    ) -> TaskExecutionResult:
        cleanup_errors = self._cleanup_partial(session, transport)
        self._clear_active()
        payload = {
            "cancellation_stage": cancellation_stage,
            "transport_open_stage": open_result.stage,
            "resource_released": not cleanup_errors,
        }
        if not cleanup_errors:
            return TaskExecutionResult(
                task_id,
                TaskFinalStatus.CANCELLED,
                "Connection cancelled",
                f"Connection cancelled during {cancellation_stage}",
                step_results=step_results,
                payload=payload,
                cancel_requested=True,
            )
        error = GuiRuntimeError(
            "CONNECT_CANCELLATION_CLEANUP_FAILED",
            "Connection cancellation cleanup failed",
            cancellation_stage,
            ErrorDisposition.SHOW_ONLY,
            task_id,
            True,
            details={
                **payload,
                "cleanup_errors": cleanup_errors,
                "cleanup_pending": self._pending_close is not None,
            },
        )
        return TaskExecutionResult(
            task_id,
            TaskFinalStatus.FAILED,
            "Connection cancellation cleanup failed",
            error.message,
            step_results=step_results,
            error=error,
            cancel_requested=True,
        )

    def _connect_failure(
        self,
        task_id,
        session,
        transport,
        code: str,
        message: str,
        stage: str,
        *,
        step_results: tuple[object, ...] = (),
        details: dict[str, object] | None = None,
    ) -> TaskExecutionResult:
        cleanup_errors = self._cleanup_partial(session, transport)
        self._clear_active()
        error_details = dict(details or {})
        if cleanup_errors:
            error_details["cleanup_errors"] = cleanup_errors
        error_details["cleanup_pending"] = self._pending_close is not None
        return self._failure(task_id, code, message, stage=stage, details=error_details, step_results=step_results)

    def _connect_settings_failure(self, task_id, message: str) -> TaskExecutionResult:
        return self._failure(
            task_id,
            "INVALID_CONNECTION_SETTINGS",
            message,
            details={"cleanup_pending": self._pending_close is not None},
        )

    def _close(self, task_id, request, progress, default_step: str, default_title: str) -> TaskExecutionResult:
        step_id = getattr(request, "step_id", default_step)
        title = getattr(request, "title", default_title)
        self._clear_metadata_status()
        self._publish(task_id, step_id, TaskStepState.STARTED, step_id.upper(), title, progress)
        resource = self._session or self._transport or self._pending_close
        self._pending_close = resource
        self.invalidate_prepared_image_cache()
        self._clear_active()
        if resource is None:
            self._publish(task_id, step_id, TaskStepState.COMPLETED, step_id.upper(), "Already disconnected", progress)
            return TaskExecutionResult(task_id, TaskFinalStatus.SUCCEEDED, title, "No active connection")
        try:
            self._close_resource(resource)
        except Exception as exc:
            return self._failure(
                task_id,
                "SERIAL_CLOSE_FAILED",
                str(exc),
                stage=step_id,
                summary="Shutdown failed" if default_step == "shutdown" else "Disconnect failed",
                details={
                    "exception_type": type(exc).__name__,
                    "cleanup_pending": True,
                },
            )
        self._pending_close = None
        self._publish(task_id, step_id, TaskStepState.COMPLETED, step_id.upper(), "Disconnected", progress)
        return TaskExecutionResult(task_id, TaskFinalStatus.SUCCEEDED, title, "Disconnected")

    def _cleanup_partial(self, session, transport) -> tuple[str, ...]:
        errors: list[str] = []
        self._pending_close = None
        if session is not None:
            try:
                self._close_resource(session)
            except Exception as exc:
                errors.append(f"session: {exc}")
            else:
                return ()
        if transport is not None:
            try:
                self._close_resource(transport)
            except Exception as exc:
                errors.append(f"transport: {exc}")
                self._pending_close = transport
            else:
                session_transport = getattr(getattr(session, "config", None), "transport", None)
                if session is not None and session_transport is not transport:
                    self._pending_close = session
        elif session is not None:
            self._pending_close = session
        return tuple(errors)

    @staticmethod
    def _close_resource(resource: Any) -> None:
        close = getattr(resource, "disconnect", None) or getattr(resource, "close", None)
        if close is None:
            raise TypeError("runtime resource is not closeable")
        close()

    def _clear_active(self) -> None:
        self._clear_metadata_status()
        connection = self._runtime_v2_store.snapshot().connection
        if connection is not None:
            self._runtime_v2_dispatcher.dispatch(
                ConnectionClosed(connection.connection_id, connection.generation)
            )
        with self._image_lock:
            self._clean_verify_credential = None
        self._session = None
        self._transport = None
        self._target = None
        self._device_info = None
        self._connection_info = None

    def _prepare_flash_image(self, task_id, request: PrepareFlashImageRequest, progress) -> TaskExecutionResult:
        with self._image_lock:
            if self._image_selection_revision is None:
                self._image_selection_revision = request.selection_revision
            if request.selection_revision != self._image_selection_revision:
                raise _ImagePreparationFailure(
                    "IMAGE_SELECTION_CHANGED",
                    "The selected image changed before preparation started",
                )
            self._prepared_flash_image = None
            self._prepared_image_summary = None
        self._publish(
            task_id,
            "prepare_flash_image",
            TaskStepState.STARTED,
            "PREPARE_FLASH_IMAGE",
            "Preparing CPU1 App image",
            progress,
        )
        if not isinstance(request.source_path, str) or not request.source_path.strip():
            raise _ImagePreparationFailure("INVALID_IMAGE_PATH", "Image path must not be empty")
        try:
            path = Path(request.source_path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise _ImagePreparationFailure("INVALID_IMAGE_PATH", str(exc)) from exc
        source_kind = self._source_kind(path)
        before = self._fingerprint(path)
        if source_kind is ImageSourceKind.OUT and self._global_settings_error is not None:
            raise _ImagePreparationFailure(
                "GLOBAL_SETTINGS_LOAD_FAILED", self._global_settings_error
            )

        hex2000_executable: Path | None = None
        hex2000_source = Hex2000Source.NOT_USED
        if source_kind is ImageSourceKind.OUT:
            try:
                hex2000_executable = locate_hex2000(
                    self._hex2000_executable_path or None,
                    environ=os.environ,
                )
            except Hex2000ConfigurationError as exc:
                raise _ImagePreparationFailure("HEX2000_CONFIGURATION_INVALID", str(exc)) from exc
            except Hex2000NotFoundError as exc:
                raise _ImagePreparationFailure("HEX2000_NOT_FOUND", str(exc)) from exc
            hex2000_source = (
                Hex2000Source.GLOBAL_SETTINGS
                if self._hex2000_executable_path
                else Hex2000Source.C2000_CG_ROOT
            )

        try:
            prepared = prepare_flash_app_image(
                path,
                target=CPU1_PROFILE,
                hex2000=str(hex2000_executable) if hex2000_executable else None,
                work_dir=self._sci8_temp_dir or None,
            )
        except Sci8ParseError as exc:
            raise _ImagePreparationFailure("IMAGE_PARSE_FAILED", str(exc)) from exc
        except Hex2000Error as exc:
            raise _ImagePreparationFailure("IMAGE_CONVERSION_FAILED", str(exc)) from exc
        except FileNotFoundError as exc:
            raise _ImagePreparationFailure(
                "IMAGE_CHANGED_DURING_PREPARATION",
                "The source image was deleted during preparation",
            ) from exc
        except OSError as exc:
            raise _ImagePreparationFailure("IMAGE_FILE_ACCESS_FAILED", str(exc)) from exc
        except ValueError as exc:
            raise _ImagePreparationFailure("IMAGE_VALIDATION_FAILED", str(exc)) from exc
        after = self._fingerprint(path, during_preparation=True)
        if before != after:
            raise _ImagePreparationFailure(
                "IMAGE_CHANGED_DURING_PREPARATION",
                "The source image changed during preparation",
            )
        summary = self._build_image_summary(
            request,
            prepared,
            source_kind,
            after,
            hex2000_source,
            hex2000_executable,
        )
        self._publish(
            task_id,
            "prepare_flash_image",
            TaskStepState.COMPLETED,
            "PREPARE_FLASH_IMAGE",
            "CPU1 App image prepared",
            progress,
        )
        result = TaskExecutionResult(
            task_id,
            TaskFinalStatus.SUCCEEDED,
            "Image prepared",
            "CPU1 App image prepared",
            payload=summary,
        )
        with self._image_lock:
            if request.selection_revision != self._image_selection_revision:
                raise _ImagePreparationFailure(
                    "IMAGE_SELECTION_CHANGED", "The selected image changed during preparation"
                )
            self._prepared_flash_image = prepared
            self._prepared_image_summary = summary
        return result

    def _prepare_ram_image(self, task_id, request: PrepareRamImageRequest, progress) -> TaskExecutionResult:
        with self._image_lock:
            if request.selection_revision != self._ram_selection_revisions[request.target_key]:
                raise _ImagePreparationFailure("IMAGE_SELECTION_CHANGED", "The RAM image selection changed")
            self._prepared_ram_images.pop(request.target_key, None)
        self._publish(task_id, "prepare_ram_image", TaskStepState.STARTED, "PREPARE_RAM_IMAGE", "Preparing RAM image", progress)
        path, source_kind, before, executable, executable_source = self._resolve_local_image(request.source_path)
        target = CPU1_PROFILE if request.target_key == "cpu1" else CPU2_PROFILE
        try:
            if source_kind is ImageSourceKind.OUT:
                temp_root = self._sci8_temp_dir or None
                if temp_root:
                    Path(temp_root).mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="advanced_ram_sci8_", dir=temp_root) as work:
                    prepared = self._prepare_ram_operation(
                        path,
                        target=target,
                        hex2000=str(executable),
                        sci8_txt=Path(work) / f"{path.stem}.sci8.txt",
                    )
            else:
                prepared = self._prepare_ram_operation(path, target=target)
        except Sci8ParseError as exc:
            raise _ImagePreparationFailure("IMAGE_PARSE_FAILED", str(exc)) from exc
        except Hex2000Error as exc:
            raise _ImagePreparationFailure("IMAGE_CONVERSION_FAILED", str(exc)) from exc
        except (FileNotFoundError, OSError) as exc:
            raise _ImagePreparationFailure("IMAGE_FILE_ACCESS_FAILED", str(exc)) from exc
        except ValueError as exc:
            raise _ImagePreparationFailure("IMAGE_VALIDATION_FAILED", str(exc)) from exc
        after = self._fingerprint(path, during_preparation=True)
        if before != after:
            raise _ImagePreparationFailure("IMAGE_CHANGED_DURING_PREPARATION", "The source image changed during preparation")
        summary = PreparedRamImageSummary(
            request.target_key,
            request.selection_revision,
            after.resolved_path,
            source_kind,
            after,
            prepared.entry_point,
            prepared.total_words,
            prepared.image_crc32,
            executable_source,
            str(executable) if executable else None,
        )
        self._publish(task_id, "prepare_ram_image", TaskStepState.COMPLETED, "PREPARE_RAM_IMAGE", "RAM image prepared", progress)
        with self._image_lock:
            if request.selection_revision != self._ram_selection_revisions[request.target_key]:
                raise _ImagePreparationFailure("IMAGE_SELECTION_CHANGED", "The RAM image selection changed during preparation")
            self._prepared_ram_images[request.target_key] = (prepared, summary)
        return TaskExecutionResult(task_id, TaskFinalStatus.SUCCEEDED, "RAM image prepared", "RAM image prepared", payload=summary)

    def _prepare_advanced_flash_image(
        self, task_id, request: PrepareAdvancedFlashImageRequest, progress
    ) -> TaskExecutionResult:
        with self._image_lock:
            if (
                request.selection_revision != self._advanced_flash_selection_revisions[request.target_key]
                or request.configuration_revision != self._configuration_revision
            ):
                raise _ImagePreparationFailure("IMAGE_SELECTION_CHANGED", "The Advanced Flash image selection changed")
            self._prepared_advanced_flash_images.pop(request.target_key, None)
            if request.target_key == "cpu1":
                self._clean_verify_credential = None
        self._publish(
            task_id, "prepare_advanced_flash_image", TaskStepState.STARTED,
            "PREPARE_ADVANCED_FLASH_IMAGE", "Preparing Advanced Flash image", progress,
        )
        path, source_kind, before, executable, executable_source = self._resolve_local_image(request.source_path)
        target = CPU1_PROFILE if request.target_key == "cpu1" else CPU2_PROFILE
        try:
            prepared = prepare_flash_app_image(
                path,
                target=target,
                hex2000=str(executable) if executable else None,
                work_dir=self._sci8_temp_dir or None,
            )
        except Sci8ParseError as exc:
            raise _ImagePreparationFailure("IMAGE_PARSE_FAILED", str(exc)) from exc
        except Hex2000Error as exc:
            raise _ImagePreparationFailure("IMAGE_CONVERSION_FAILED", str(exc)) from exc
        except (FileNotFoundError, OSError) as exc:
            raise _ImagePreparationFailure("IMAGE_FILE_ACCESS_FAILED", str(exc)) from exc
        except ValueError as exc:
            raise _ImagePreparationFailure("UNSUPPORTED_OR_INVALID_IMAGE", str(exc)) from exc
        after = self._fingerprint(path, during_preparation=True)
        if before != after:
            raise _ImagePreparationFailure("IMAGE_CHANGED_DURING_PREPARATION", "The source image changed during preparation")
        image_mask = image_sector_mask(prepared.image)
        summary = PreparedAdvancedFlashImageSummary(
            request.target_key,
            after.resolved_path,
            request.selection_revision,
            request.configuration_revision,
            source_kind,
            after,
            prepared.identity.entry_point,
            prepared.identity.image_size_words,
            prepared.identity.image_crc32,
            prepared.identity.app_end,
            image_mask,
            prepared.sector_mask,
            executable_source,
            str(executable) if executable else None,
        )
        with self._image_lock:
            if (
                request.selection_revision != self._advanced_flash_selection_revisions[request.target_key]
                or request.configuration_revision != self._configuration_revision
            ):
                raise _ImagePreparationFailure("IMAGE_SELECTION_CHANGED", "The Advanced Flash image selection changed during preparation")
            self._prepared_advanced_flash_images[request.target_key] = (prepared, summary)
        self._publish(
            task_id, "prepare_advanced_flash_image", TaskStepState.COMPLETED,
            "PREPARE_ADVANCED_FLASH_IMAGE", "Advanced Flash image prepared", progress,
        )
        return TaskExecutionResult(
            task_id, TaskFinalStatus.SUCCEEDED, "Advanced Flash image prepared",
            "Advanced Flash image prepared", payload=summary,
        )

    def _prepare_flash_service(
        self, task_id, request: PrepareFlashServiceRequest, progress
    ) -> TaskExecutionResult:
        with self._image_lock:
            if (
                request.configuration_revision != self._service_configuration_revision
                or request.tool_configuration_revision != self._configuration_revision
            ):
                raise _ImagePreparationFailure("SERVICE_CONFIGURATION_CHANGED", "The Flash Service inputs changed")
            self._prepared_service_image = None
            self._prepared_service_summary = None
        self._publish(
            task_id, "prepare_flash_service", TaskStepState.STARTED,
            "PREPARE_FLASH_SERVICE", "Preparing CPU1 Flash Service", progress,
        )
        image_path, source_kind, image_before, executable, executable_source = self._resolve_local_image(
            request.service_image_path
        )
        if not request.service_map_path:
            raise _ImagePreparationFailure("INVALID_SERVICE_MAP_PATH", "Service map path must not be empty")
        try:
            map_path = Path(request.service_map_path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise _ImagePreparationFailure("INVALID_SERVICE_MAP_PATH", str(exc)) from exc
        map_before = self._fingerprint(map_path)
        kwargs = {
            "target": CPU1_PROFILE,
            "hex2000": str(executable) if executable else None,
        }
        if request.descriptor_symbol:
            kwargs["descriptor_symbol"] = request.descriptor_symbol
        try:
            prepared = prepare_service_image(image_path, map_path, **kwargs)
        except Sci8ParseError as exc:
            raise _ImagePreparationFailure("IMAGE_PARSE_FAILED", str(exc)) from exc
        except Hex2000Error as exc:
            raise _ImagePreparationFailure("IMAGE_CONVERSION_FAILED", str(exc)) from exc
        except (FileNotFoundError, OSError) as exc:
            raise _ImagePreparationFailure("SERVICE_FILE_ACCESS_FAILED", str(exc)) from exc
        except ValueError as exc:
            raise _ImagePreparationFailure("SERVICE_VALIDATION_FAILED", str(exc)) from exc
        image_after = self._fingerprint(image_path, during_preparation=True)
        map_after = self._fingerprint(map_path, during_preparation=True)
        if image_before != image_after or map_before != map_after:
            raise _ImagePreparationFailure("SERVICE_CHANGED_DURING_PREPARATION", "A Flash Service input changed during preparation")
        summary = PreparedFlashServiceSummary(
            request.target_key,
            image_after.resolved_path,
            map_after.resolved_path,
            request.descriptor_symbol,
            request.configuration_revision,
            request.tool_configuration_revision,
            source_kind,
            image_after,
            map_after,
            prepared.descriptor_address,
            prepared.api_table_address,
            prepared.crc_patch_address,
            prepared.total_words,
            prepared.expected_crc32,
            executable_source,
            str(executable) if executable else None,
        )
        with self._image_lock:
            if (
                request.configuration_revision != self._service_configuration_revision
                or request.tool_configuration_revision != self._configuration_revision
            ):
                raise _ImagePreparationFailure("SERVICE_CONFIGURATION_CHANGED", "The Flash Service inputs changed during preparation")
            self._prepared_service_image = prepared
            self._prepared_service_summary = summary
        self._publish(
            task_id, "prepare_flash_service", TaskStepState.COMPLETED,
            "PREPARE_FLASH_SERVICE", "CPU1 Flash Service prepared", progress,
        )
        return TaskExecutionResult(
            task_id, TaskFinalStatus.SUCCEEDED, "CPU1 Flash Service prepared",
            "CPU1 Flash Service prepared", payload=summary,
        )

    def _resolve_local_image(self, source_path: str):
        if not source_path:
            raise _ImagePreparationFailure("INVALID_IMAGE_PATH", "Image path must not be empty")
        try:
            path = Path(source_path).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise _ImagePreparationFailure("INVALID_IMAGE_PATH", str(exc)) from exc
        source_kind = self._source_kind(path)
        before = self._fingerprint(path)
        if source_kind is ImageSourceKind.TXT:
            return path, source_kind, before, None, Hex2000Source.NOT_USED
        if self._global_settings_error is not None:
            raise _ImagePreparationFailure("GLOBAL_SETTINGS_LOAD_FAILED", self._global_settings_error)
        try:
            executable = locate_hex2000(self._hex2000_executable_path or None, environ=os.environ)
        except Hex2000ConfigurationError as exc:
            raise _ImagePreparationFailure("HEX2000_CONFIGURATION_INVALID", str(exc)) from exc
        except Hex2000NotFoundError as exc:
            raise _ImagePreparationFailure("HEX2000_NOT_FOUND", str(exc)) from exc
        source = Hex2000Source.GLOBAL_SETTINGS if self._hex2000_executable_path else Hex2000Source.C2000_CG_ROOT
        return path, source_kind, before, executable, source

    def _execute_ram_operation(self, task_id, request, cancellation, progress) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None or captured[3] != request.target_key:
            return self._ram_request_failure(task_id, "STALE_CONNECTION", "The connected target changed", request)
        with self._image_lock:
            cached = self._prepared_ram_images.get(request.target_key)
            revision = self._ram_selection_revisions[request.target_key]
        if cached is None or revision != request.selection_revision:
            return self._ram_request_failure(task_id, "PREPARED_RAM_IMAGE_REQUIRED", "Prepare the current target RAM image first", request)
        image, summary = cached
        try:
            image_changed = self._fingerprint(Path(summary.source_path)) != summary.source_fingerprint
        except _ImagePreparationFailure:
            image_changed = True
        if image_changed:
            self._clear_ram_cache_for_revision(request.target_key, request.selection_revision)
            return self._ram_request_failure(task_id, "IMAGE_CHANGED", "The source RAM image changed", request)

        fields = (
            ("ram_load_begin", "ram_load_data", "ram_load_end")
            if isinstance(request, LoadAdvancedRamImageRequest)
            else (("ram_check_crc",) if isinstance(request, CheckAdvancedRamCrcRequest) else ("run_ram",))
        )
        if any(getattr(captured[1].command_set, field) is None for field in fields):
            return self._ram_request_failure(task_id, "UNSUPPORTED_OPERATION", "The current target does not support this RAM operation", request)

        step_id = request.step_id
        self._publish(task_id, step_id, TaskStepState.STARTED, step_id.upper(), request.title, progress)
        last_update = None

        def report(event) -> None:
            nonlocal last_update
            last_update = operation_progress_to_task_update(task_id, step_id, event)
            if progress is not None:
                progress(last_update)

        context = OperationContext(
            captured[0],
            captured[1],
            progress=report if isinstance(request, LoadAdvancedRamImageRequest) else None,
            cancellation=cancellation if isinstance(request, LoadAdvancedRamImageRequest) else None,
        )
        if isinstance(request, LoadAdvancedRamImageRequest):
            result = self._load_ram_operation(context, LoadRamImageRequest(image))
        elif isinstance(request, CheckAdvancedRamCrcRequest):
            result = self._check_ram_crc_operation(context, CheckRamCrcRequest(image))
        else:
            result = self._run_ram_operation(context, RunRamImageRequest(image))
        if not isinstance(result, OperationResult):
            raise TypeError("RAM operation returned an invalid result")
        if self._status_connection(request.connection_id, captured) is None:
            return self._ram_request_failure(task_id, "STALE_CONNECTION", "The connection changed during the RAM operation", request)
        if result.ok:
            if last_update is None:
                self._publish(task_id, step_id, TaskStepState.COMPLETED, result.stage, result.operation, progress)
            elif progress is not None:
                progress(replace(last_update, step_state=TaskStepState.COMPLETED))
        payload = AdvancedRamOperationSnapshot(request.connection_id, request.target_key, request.selection_revision, result)
        action = TaskCompletionAction.RELEASE_CONNECTION if isinstance(request, RunAdvancedRamImageRequest) else TaskCompletionAction.NONE
        return operation_result_to_task_result(
            task_id,
            result,
            success_summary=request.title,
            success_message=result.stage,
            payload=payload,
            completion_action=action,
        )

    def _execute_advanced_flash_operation(
        self, task_id, request, cancellation, progress
    ) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None:
            return self._advanced_flash_request_failure(
                task_id, "STALE_CONNECTION", "The active connection changed", request
            )
        if request.target_key != "cpu1":
            return self._advanced_flash_request_failure(
                task_id, "UNSUPPORTED_OPERATION", "Advanced Flash operations support CPU1 only", request
            )
        if captured[3] != request.target_key:
            return self._advanced_flash_request_failure(
                task_id, "STALE_TARGET", "The connected target changed", request
            )

        with self._image_lock:
            image_cached = self._prepared_advanced_flash_images.get("cpu1")
            service_image = self._prepared_service_image
            service_summary = self._prepared_service_summary
            image_revision = self._advanced_flash_selection_revisions["cpu1"]
            service_revision = self._service_configuration_revision
            tool_revision = self._configuration_revision
        if image_cached is None:
            return self._advanced_flash_request_failure(
                task_id, "PREPARED_FLASH_IMAGE_REQUIRED", "Prepare the CPU1 Advanced Flash image first", request
            )
        image, image_summary = image_cached
        if (
            image_revision != request.image_selection_revision
            or image_summary.selection_revision != request.image_selection_revision
            or image_summary.configuration_revision != request.image_tool_configuration_revision
            or tool_revision != request.image_tool_configuration_revision
        ):
            return self._advanced_flash_request_failure(
                task_id, "STALE_IMAGE_CONFIGURATION", "The Advanced Flash image configuration changed", request
            )
        if service_image is None or service_summary is None:
            return self._advanced_flash_request_failure(
                task_id, "PREPARED_FLASH_SERVICE_REQUIRED", "Prepare the CPU1 Flash Service first", request
            )
        if (
            service_revision != request.service_configuration_revision
            or service_summary.configuration_revision != request.service_configuration_revision
            or service_summary.tool_configuration_revision != request.service_tool_configuration_revision
            or tool_revision != request.service_tool_configuration_revision
        ):
            return self._advanced_flash_request_failure(
                task_id, "STALE_SERVICE_CONFIGURATION", "The Flash Service configuration changed", request
            )

        try:
            image_changed = self._fingerprint(Path(image_summary.source_path)) != image_summary.source_fingerprint
        except _ImagePreparationFailure:
            image_changed = True
        if image_changed:
            self._clear_advanced_flash_cache_for_revision("cpu1", request.image_selection_revision)
            return self._advanced_flash_request_failure(
                task_id, "IMAGE_CHANGED", "The Advanced Flash source image changed", request
            )
        try:
            service_changed = (
                self._fingerprint(Path(service_summary.service_image_path)) != service_summary.image_fingerprint
                or self._fingerprint(Path(service_summary.service_map_path)) != service_summary.map_fingerprint
            )
        except _ImagePreparationFailure:
            service_changed = True
        if service_changed:
            self._clear_service_cache_for_revision(request.service_configuration_revision)
            return self._advanced_flash_request_failure(
                task_id, "SERVICE_CHANGED", "A Flash Service source file changed", request
            )

        with self._image_lock:
            current_image = self._prepared_advanced_flash_images.get("cpu1")
            if (
                current_image is None
                or current_image[0] is not image
                or current_image[1] != image_summary
                or self._advanced_flash_selection_revisions["cpu1"]
                != request.image_selection_revision
                or self._configuration_revision
                != request.image_tool_configuration_revision
            ):
                return self._advanced_flash_request_failure(
                    task_id, "STALE_IMAGE_CONFIGURATION", "The Advanced Flash image configuration changed", request
                )
            if (
                self._prepared_service_image is not service_image
                or self._prepared_service_summary != service_summary
                or self._service_configuration_revision
                != request.service_configuration_revision
                or self._configuration_revision
                != request.service_tool_configuration_revision
            ):
                return self._advanced_flash_request_failure(
                    task_id, "STALE_SERVICE_CONFIGURATION", "The Flash Service configuration changed", request
                )

        flash = captured[1].memory_map.flash
        if flash is None:
            return self._advanced_flash_request_failure(
                task_id, "UNSUPPORTED_OPERATION", "The current target has no Flash layout", request
            )
        common = (
            "get_service_status",
            "service_attach",
            "ram_load_begin",
            "ram_load_data",
            "ram_load_end",
            "ram_check_crc",
        )
        required = (
            (*common, "erase")
            if isinstance(request, EraseAdvancedFlashRequest)
            else (*common, "program_begin", "program_data", "program_end")
            if isinstance(request, ProgramAdvancedFlashRequest)
            else (*common, "verify_begin", "verify_data", "verify_end")
        )
        if any(getattr(captured[1].command_set, field) is None for field in required):
            return self._advanced_flash_request_failure(
                task_id, "UNSUPPORTED_OPERATION", "The current target lacks required Flash capabilities", request
            )

        erase_scope = None
        erase_mask = None
        if isinstance(request, EraseAdvancedFlashRequest):
            erase_scope = request.erase_scope
            if erase_scope is AdvancedFlashEraseScope.REQUIRED_APP_SECTORS:
                erase_mask = image.sector_mask | flash.metadata_sector_mask
            elif erase_scope is AdvancedFlashEraseScope.ENTIRE_APPLICATION_REGION:
                erase_mask = flash.allowed_erase_mask
            elif erase_scope is AdvancedFlashEraseScope.CUSTOM_SECTOR_MASK:
                erase_mask = request.custom_sector_mask
            else:
                return self._advanced_flash_request_failure(
                    task_id, "INVALID_ERASE_SCOPE", "The erase scope is invalid", request
                )
            if (
                erase_mask == 0
                or erase_mask & flash.forbidden_erase_mask
                or erase_mask & ~flash.allowed_erase_mask
            ):
                return self._advanced_flash_request_failure(
                    task_id, "FORBIDDEN_SECTOR", "The erase mask includes a forbidden sector", request
                )

        step_id = request.step_id
        with self._image_lock:
            self._clean_verify_credential = None
        if isinstance(request, (EraseAdvancedFlashRequest, ProgramAdvancedFlashRequest)):
            self._clear_metadata_status()
        self._publish(task_id, step_id, TaskStepState.STARTED, step_id.upper(), request.title, progress)
        last_update = None

        def report(event) -> None:
            nonlocal last_update
            last_update = operation_progress_to_task_update(task_id, step_id, event)
            last_update = replace(
                last_update,
                current=None,
                total=None,
                progress_mode=ProgressMode.INDETERMINATE,
            )
            if progress is not None:
                progress(last_update)

        context = FlashOperationContext(
            session=captured[0],
            target=captured[1],
            progress=report,
            cancellation=cancellation,
            service=service_image,
        )
        if isinstance(request, EraseAdvancedFlashRequest):
            if request.erase_scope is AdvancedFlashEraseScope.REQUIRED_APP_SECTORS:
                result = self._erase_flash_image_area_operation(
                    context, EraseFlashImageAreaRequest(image)
                )
            else:
                result = self._erase_sector_mask_operation(
                    context, EraseSectorMaskRequest(erase_mask)
                )
            operation_type = AdvancedFlashOperationType.ERASE
        elif isinstance(request, ProgramAdvancedFlashRequest):
            result = self._program_flash_operation(context, ProgramFlashImageRequest(image))
            operation_type = AdvancedFlashOperationType.PROGRAM_ONLY
        else:
            result = self._verify_flash_operation(context, VerifyFlashImageRequest(image))
            operation_type = AdvancedFlashOperationType.VERIFY_ONLY
        if not isinstance(result, OperationResult):
            raise TypeError("Advanced Flash operation returned an invalid result")
        if self._status_connection(request.connection_id, captured) is None:
            return self._advanced_flash_request_failure(
                task_id, "STALE_CONNECTION", "The connection changed during the Flash operation", request
            )
        if isinstance(request, VerifyAdvancedFlashRequest):
            self._store_clean_verify_credential(request, captured, image, image_summary, result)
        if result.completion in {
            OperationCompletion.SUCCEEDED,
            OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
        }:
            if last_update is None:
                self._publish(task_id, step_id, TaskStepState.COMPLETED, result.stage, result.operation, progress)
            elif progress is not None:
                progress(replace(last_update, step_state=TaskStepState.COMPLETED))
        payload = AdvancedFlashOperationSnapshot(
            request.connection_id,
            request.target_key,
            request.image_selection_revision,
            request.image_tool_configuration_revision,
            request.service_configuration_revision,
            request.service_tool_configuration_revision,
            operation_type,
            result,
            operation_result_to_dict(result),
            erase_scope,
            erase_mask,
        )
        return operation_result_to_task_result(
            task_id,
            result,
            success_summary=request.title,
            success_message=result.stage,
            payload=payload,
            completion_action=TaskCompletionAction.NONE,
        )

    def _store_clean_verify_credential(self, request, captured, image, summary, result) -> None:
        result_words = result.summary.get("total_words")
        if (
            result.completion is not OperationCompletion.SUCCEEDED
            or not result.ok
            or result.target != captured[1].name
            or (
                result_words is not None
                and (type(result_words) is not int or result_words != image.identity.image_size_words)
            )
        ):
            return
        try:
            fingerprint = self._fingerprint(Path(summary.source_path))
        except _ImagePreparationFailure:
            return
        with self._image_lock:
            current = self._prepared_advanced_flash_images.get("cpu1")
            if not (
                self._status_connection(request.connection_id, captured) is not None
                and captured[3] == "cpu1"
                and current is not None
                and current[0] is image
                and current[1] == summary
                and self._advanced_flash_selection_revisions["cpu1"]
                == request.image_selection_revision
                and self._configuration_revision
                == request.image_tool_configuration_revision
                and summary.source_fingerprint == fingerprint
                and (
                    image.identity.entry_point,
                    image.identity.image_size_words,
                    image.identity.image_crc32,
                    image.identity.app_end,
                )
                == (
                    summary.entry_point,
                    summary.image_size_words,
                    summary.image_crc32,
                    summary.app_end,
                )
            ):
                return
            self._clean_verify_credential = CleanVerifyCredential(
                uuid4().hex,
                request.connection_id,
                "cpu1",
                request.image_selection_revision,
                request.image_tool_configuration_revision,
                summary.source_fingerprint,
                summary.entry_point,
                summary.image_size_words,
                summary.image_crc32,
                summary.app_end,
            )

    def _execute_advanced_metadata_operation(
        self, task_id, request, cancellation, progress
    ) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None:
            return self._metadata_request_failure(
                task_id, "STALE_CONNECTION", "The active connection changed", request
            )
        if request.target_key != "cpu1":
            return self._metadata_request_failure(
                task_id, "UNSUPPORTED_OPERATION", "Advanced Metadata supports CPU1 only", request
            )
        if captured[3] != "cpu1":
            return self._metadata_request_failure(
                task_id, "STALE_TARGET", "The connected target changed", request
            )
        if captured[1].cpu_id != CPU1_PROFILE.cpu_id:
            return self._metadata_request_failure(
                task_id, "STALE_TARGET", "The active Target is not CPU1", request
            )

        with self._image_lock:
            image_cached = self._prepared_advanced_flash_images.get("cpu1")
            service = self._prepared_service_image
            service_summary = self._prepared_service_summary
            image_revision = self._advanced_flash_selection_revisions["cpu1"]
            service_revision = self._service_configuration_revision
            tool_revision = self._configuration_revision
            credential = self._clean_verify_credential
        if image_cached is None:
            return self._metadata_request_failure(
                task_id, "PREPARED_FLASH_IMAGE_REQUIRED", "Prepare the CPU1 Advanced Flash image first", request
            )
        image, image_summary = image_cached
        if (
            image_revision != request.image_selection_revision
            or image_summary.selection_revision != request.image_selection_revision
            or image_summary.configuration_revision != request.image_tool_configuration_revision
            or tool_revision != request.image_tool_configuration_revision
        ):
            return self._metadata_request_failure(
                task_id, "STALE_IMAGE_CONFIGURATION", "The Advanced Flash image configuration changed", request
            )
        if service is None or service_summary is None:
            return self._metadata_request_failure(
                task_id, "PREPARED_FLASH_SERVICE_REQUIRED", "Prepare the CPU1 Flash Service first", request
            )
        if (
            service_revision != request.service_configuration_revision
            or service_summary.configuration_revision != request.service_configuration_revision
            or service_summary.tool_configuration_revision != request.service_tool_configuration_revision
            or tool_revision != request.service_tool_configuration_revision
        ):
            return self._metadata_request_failure(
                task_id, "STALE_SERVICE_CONFIGURATION", "The Flash Service configuration changed", request
            )
        try:
            app_fingerprint = self._fingerprint(Path(image_summary.source_path))
        except _ImagePreparationFailure:
            app_fingerprint = None
        if app_fingerprint != image_summary.source_fingerprint:
            self._clear_advanced_flash_cache_for_revision("cpu1", request.image_selection_revision)
            return self._metadata_request_failure(
                task_id, "IMAGE_CHANGED", "The Advanced Flash source image changed", request
            )
        try:
            service_changed = (
                self._fingerprint(Path(service_summary.service_image_path))
                != service_summary.image_fingerprint
                or self._fingerprint(Path(service_summary.service_map_path))
                != service_summary.map_fingerprint
            )
        except _ImagePreparationFailure:
            service_changed = True
        if service_changed:
            self._clear_service_cache_for_revision(request.service_configuration_revision)
            return self._metadata_request_failure(
                task_id, "SERVICE_CHANGED", "A Flash Service source file changed", request
            )

        commands = captured[1].command_set
        required = (
            "get_service_status",
            "service_attach",
            "ram_load_begin",
            "ram_load_data",
            "ram_load_end",
            "ram_check_crc",
            "get_metadata_summary",
            "metadata_append_record",
        )
        if any(getattr(commands, field, None) is None for field in required):
            return self._metadata_request_failure(
                task_id, "UNSUPPORTED_OPERATION", "The current target lacks required Metadata capabilities", request
            )

        with self._image_lock:
            if not (
                self._prepared_advanced_flash_images.get("cpu1") == image_cached
                and self._prepared_advanced_flash_images["cpu1"][0] is image
                and self._advanced_flash_selection_revisions["cpu1"] == request.image_selection_revision
                and self._configuration_revision == request.image_tool_configuration_revision
            ):
                return self._metadata_request_failure(
                    task_id, "STALE_IMAGE_CONFIGURATION", "Prepared inputs changed before Metadata execution", request
                )
            if not (
                self._prepared_service_image is service
                and self._prepared_service_summary == service_summary
                and self._service_configuration_revision == request.service_configuration_revision
                and self._configuration_revision == request.service_tool_configuration_revision
            ):
                return self._metadata_request_failure(
                    task_id, "STALE_SERVICE_CONFIGURATION", "Prepared Flash Service changed before Metadata execution", request
                )
        if self._status_connection(request.connection_id, captured) is None:
            return self._metadata_request_failure(
                task_id, "STALE_CONNECTION", "The active connection changed before Metadata execution", request
            )

        operation_type: AdvancedMetadataOperationType
        verification_token = None
        if isinstance(request, WriteAdvancedImageValidRequest):
            operation_type = AdvancedMetadataOperationType.WRITE_IMAGE_VALID
            verification_token = request.verification_token
            if not self._credential_matches(credential, request, image_summary):
                return self._metadata_request_failure(
                    task_id, "CLEAN_VERIFY_REQUIRED", "Run a clean Verify Only for this image first", request
                )
            operation = self._append_image_valid_operation
            operation_request = AppendImageValidRequest(image)
        elif isinstance(request, WriteAdvancedBootAttemptRequest):
            operation_type = AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT
            operation = self._append_boot_attempt_operation
            operation_request = AppendBootAttemptRequest(image.identity)
        else:
            operation_type = AdvancedMetadataOperationType.WRITE_APP_CONFIRMED
            operation = self._append_app_confirmed_operation
            operation_request = AppendAppConfirmedRequest(image.identity)

        step_id = request.step_id
        self._clear_metadata_status()
        self._publish(task_id, step_id, TaskStepState.STARTED, step_id.upper(), request.title, progress)
        last_update = None

        def report(event) -> None:
            nonlocal last_update
            last_update = replace(
                operation_progress_to_task_update(task_id, step_id, event),
                current=None,
                total=None,
                progress_mode=ProgressMode.INDETERMINATE,
            )
            if progress is not None:
                progress(last_update)

        context = FlashOperationContext(
            session=captured[0],
            target=captured[1],
            progress=report,
            cancellation=cancellation,
            service=service,
        )
        primary = operation(context, operation_request)
        if not isinstance(primary, OperationResult):
            raise TypeError("Advanced Metadata operation returned an invalid result")
        if primary.completion in {
            OperationCompletion.SUCCEEDED,
            OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
        }:
            if last_update is None:
                self._publish(task_id, step_id, TaskStepState.COMPLETED, primary.stage, primary.operation, progress)
            elif progress is not None:
                progress(replace(last_update, step_state=TaskStepState.COMPLETED))

        payload = self._metadata_payload(
            request, operation_type, verification_token, image_summary, primary
        )
        if primary.completion not in {
            OperationCompletion.SUCCEEDED,
            OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
        }:
            return operation_result_to_task_result(task_id, primary, payload=payload)
        if self._status_connection(request.connection_id, captured) is None:
            return self._metadata_failure(
                task_id,
                "STALE_CONNECTION",
                "The connection changed before Metadata readback",
                "GET_METADATA_SUMMARY",
                payload,
                (primary,),
            )

        readback_step = "read_metadata_summary"
        self._publish(
            task_id, readback_step, TaskStepState.STARTED,
            "GET_METADATA_SUMMARY", "Reading Metadata Summary", progress,
        )
        readback = self._metadata_operation(OperationContext(captured[0], captured[1]))
        if not isinstance(readback, OperationResult):
            raise TypeError("Metadata readback returned an invalid result")
        payload = self._metadata_payload(
            request, operation_type, verification_token, image_summary, primary, readback
        )
        if self._status_connection(request.connection_id, captured) is None:
            return self._metadata_failure(
                task_id, "STALE_CONNECTION", "The connection changed during Metadata readback",
                "GET_METADATA_SUMMARY", payload, (primary, readback),
            )
        if not readback.ok:
            code = readback.error.code if readback.error else "METADATA_READBACK_FAILED"
            message = readback.error.message if readback.error else "Metadata readback failed"
            return self._metadata_failure(
                task_id, code, f"Metadata append may have completed but readback failed: {message}",
                readback.stage, payload, (primary, readback),
                ask_disconnect=code in {"PROTOCOL_ERROR", "TARGET_MISMATCH"},
            )

        raw = MetadataSummary(**dict(readback.summary))
        metadata_snapshot = self._metadata_snapshot(
            MetadataRefreshRequest(request.connection_id), "cpu1", readback, raw
        )
        self._publish(
            task_id, readback_step, TaskStepState.COMPLETED,
            readback.stage, readback.operation, progress,
        )
        if not self._metadata_readback_matches(
            operation_type, primary, raw, image_summary, metadata_snapshot
        ):
            payload = self._metadata_payload(
                request, operation_type, verification_token, image_summary,
                primary, readback, metadata_snapshot,
            )
            return self._metadata_failure(
                task_id, "METADATA_READBACK_MISMATCH",
                "Metadata readback does not confirm the operation result",
                "GET_METADATA_SUMMARY", payload, (primary, readback), ask_disconnect=True,
            )
        if self._status_connection(request.connection_id, captured) is None:
            return self._metadata_failure(
                task_id, "STALE_CONNECTION", "The connection changed after Metadata readback",
                "GET_METADATA_SUMMARY", payload, (primary, readback),
            )
        with self._status_lock:
            self._metadata_status_snapshot = metadata_snapshot
        payload = self._metadata_payload(
            request, operation_type, verification_token, image_summary,
            primary, readback, metadata_snapshot,
        )
        result = operation_result_to_task_result(
            task_id, primary, success_summary=request.title,
            success_message=readback.stage, payload=payload,
        )
        result = replace(result, step_results=(primary, readback), payload=payload)
        if result.status is TaskFinalStatus.COMPLETED_AFTER_CANCEL_REQUEST:
            message = "The metadata append completed after cancellation; required readback also completed."
            result = replace(
                result,
                message=message,
                warning=GuiTaskWarning(
                    "OPERATION_COMPLETED_AFTER_CANCEL_REQUEST",
                    message,
                    primary.cancellation.stage,
                    dict(result.warning.details) if result.warning else {},
                ),
            )
        return result

    @staticmethod
    def _credential_matches(credential, request, summary) -> bool:
        return bool(
            type(credential) is CleanVerifyCredential
            and credential.token == request.verification_token
            and credential.connection_id == request.connection_id
            and credential.target_key == request.target_key
            and credential.image_selection_revision == request.image_selection_revision
            and credential.image_tool_configuration_revision
            == request.image_tool_configuration_revision
            and credential.source_fingerprint == summary.source_fingerprint
            and credential.entry_point == summary.entry_point
            and credential.image_size_words == summary.image_size_words
            and credential.image_crc32 == summary.image_crc32
            and credential.app_end == summary.app_end
        )

    @staticmethod
    def _metadata_readback_matches(
        operation_type, primary, raw, summary, metadata_snapshot
    ) -> bool:
        claimed = bool(primary.summary.get("written") or primary.summary.get("already_exists"))
        if not claimed:
            return True
        image_matches = bool(
            metadata_snapshot.metadata_valid
            and metadata_snapshot.image_valid
            and raw.entry_point == summary.entry_point
            and raw.image_size_words == summary.image_size_words
            and raw.image_crc32 == summary.image_crc32
        )
        if operation_type is AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
            return image_matches
        if operation_type is AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT:
            return image_matches and raw.boot_attempt_count > 0
        return image_matches and raw.boot_attempt_count > 0 and bool(raw.app_confirmed)

    @staticmethod
    def _metadata_payload(
        request, operation_type, verification_token, summary, primary,
        readback=None, metadata_snapshot=None,
    ) -> AdvancedMetadataOperationSnapshot:
        return AdvancedMetadataOperationSnapshot(
            request.connection_id,
            request.target_key,
            request.image_selection_revision,
            request.image_tool_configuration_revision,
            request.service_configuration_revision,
            request.service_tool_configuration_revision,
            operation_type,
            verification_token,
            summary.entry_point,
            summary.image_size_words,
            summary.image_crc32,
            summary.app_end,
            primary,
            operation_result_to_dict(primary),
            readback,
            operation_result_to_dict(readback) if readback is not None else None,
            metadata_snapshot,
        )

    @staticmethod
    def _metadata_failure(
        task_id, code, message, stage, payload, step_results, *, ask_disconnect=False
    ) -> TaskExecutionResult:
        disposition = ErrorDisposition.ASK_DISCONNECT if ask_disconnect else ErrorDisposition.SHOW_ONLY
        error = GuiRuntimeError(
            code, message, stage, disposition, task_id, True,
            disposition is ErrorDisposition.ASK_DISCONNECT,
        )
        return TaskExecutionResult(
            task_id, TaskFinalStatus.FAILED, "Metadata operation failed", message,
            step_results=step_results, payload=payload, error=error,
        )

    @staticmethod
    def _metadata_request_failure(task_id, code, message, request) -> TaskExecutionResult:
        error = GuiRuntimeError(
            code, message, request.step_id, ErrorDisposition.SHOW_ONLY,
            task_id, True,
            details={
                "connection_id": request.connection_id,
                "target_key": request.target_key,
                "image_selection_revision": request.image_selection_revision,
                "image_tool_configuration_revision": request.image_tool_configuration_revision,
                "service_configuration_revision": request.service_configuration_revision,
                "service_tool_configuration_revision": request.service_tool_configuration_revision,
            },
        )
        return TaskExecutionResult(
            task_id, TaskFinalStatus.FAILED, "Metadata operation rejected", message, error=error
        )

    @staticmethod
    def _advanced_flash_request_failure(task_id, code, message, request) -> TaskExecutionResult:
        error = GuiRuntimeError(
            code,
            message,
            request.step_id,
            ErrorDisposition.SHOW_ONLY,
            task_id,
            True,
            details={
                "connection_id": request.connection_id,
                "target_key": request.target_key,
                "image_selection_revision": request.image_selection_revision,
                "image_tool_configuration_revision": request.image_tool_configuration_revision,
                "service_configuration_revision": request.service_configuration_revision,
                "service_tool_configuration_revision": request.service_tool_configuration_revision,
            },
        )
        return TaskExecutionResult(
            task_id, TaskFinalStatus.FAILED, "Advanced Flash operation rejected", message, error=error
        )

    @staticmethod
    def _ram_request_failure(task_id, code, message, request) -> TaskExecutionResult:
        error = GuiRuntimeError(
            code,
            message,
            request.step_id,
            ErrorDisposition.SHOW_ONLY,
            task_id,
            True,
            details={
                "connection_id": request.connection_id,
                "target_key": request.target_key,
                "selection_revision": request.selection_revision,
            },
        )
        return TaskExecutionResult(task_id, TaskFinalStatus.FAILED, "RAM operation rejected", message, error=error)

    def _clear_ram_cache_for_revision(self, target_key: str, selection_revision: int) -> None:
        with self._image_lock:
            if self._ram_selection_revisions[target_key] == selection_revision:
                self._prepared_ram_images.pop(target_key, None)

    def _clear_advanced_flash_cache_for_revision(self, target_key: str, selection_revision: int) -> None:
        with self._image_lock:
            if self._advanced_flash_selection_revisions[target_key] == selection_revision:
                self._prepared_advanced_flash_images.pop(target_key, None)
                if target_key == "cpu1":
                    self._clean_verify_credential = None

    def _clear_service_cache_for_revision(self, configuration_revision: int) -> None:
        with self._image_lock:
            if self._service_configuration_revision == configuration_revision:
                self._prepared_service_image = None
                self._prepared_service_summary = None

    @staticmethod
    def _source_kind(path: Path) -> ImageSourceKind:
        suffix = path.suffix.lower()
        if suffix == ".out":
            return ImageSourceKind.OUT
        if suffix == ".txt":
            return ImageSourceKind.TXT
        raise _ImagePreparationFailure(
            "UNSUPPORTED_IMAGE_TYPE", "Only .out and .txt images are supported"
        )

    @staticmethod
    def _fingerprint(path: Path, *, during_preparation: bool = False) -> SourceFileFingerprint:
        try:
            file_stat = path.stat()
            if not stat.S_ISREG(file_stat.st_mode):
                raise FileNotFoundError(path)
        except FileNotFoundError as exc:
            code = "IMAGE_CHANGED_DURING_PREPARATION" if during_preparation else "IMAGE_FILE_NOT_FOUND"
            raise _ImagePreparationFailure(code, f"Image file was not found: {path}") from exc
        except PermissionError as exc:
            raise _ImagePreparationFailure("IMAGE_FILE_ACCESS_FAILED", str(exc)) from exc
        except OSError as exc:
            raise _ImagePreparationFailure("IMAGE_FILE_ACCESS_FAILED", str(exc)) from exc
        return SourceFileFingerprint(str(path), file_stat.st_size, file_stat.st_mtime_ns)

    @staticmethod
    def _build_image_summary(
        request: PrepareFlashImageRequest,
        prepared: PreparedFlashImage,
        source_kind: ImageSourceKind,
        fingerprint: SourceFileFingerprint,
        hex2000_source: Hex2000Source,
        hex2000_executable: Path | None,
    ) -> PreparedImageSummary:
        image_mask = image_sector_mask(prepared.image)
        return PreparedImageSummary(
            target_key=request.target_key,
            selection_revision=request.selection_revision,
            source_path=fingerprint.resolved_path,
            source_kind=source_kind,
            source_fingerprint=fingerprint,
            entry_point=prepared.identity.entry_point,
            image_size_words=prepared.identity.image_size_words,
            image_crc32=prepared.identity.image_crc32,
            app_end=prepared.identity.app_end,
            image_sector_mask=image_mask,
            effective_sector_mask=prepared.sector_mask,
            image_sector_bits=tuple(bit for bit in range(32) if image_mask & (1 << bit)),
            hex2000_source=hex2000_source,
            hex2000_executable=str(hex2000_executable) if hex2000_executable else None,
        )

    def _clear_image_cache_for_revision(self, selection_revision: int) -> None:
        with self._image_lock:
            if selection_revision == self._image_selection_revision:
                self._prepared_flash_image = None
                self._prepared_image_summary = None

    @staticmethod
    def _image_failure(task_id, request, failure: _ImagePreparationFailure) -> TaskExecutionResult:
        if isinstance(request, PrepareFlashServiceRequest):
            stage = "prepare_flash_service"
            details = {
                "configuration_revision": request.configuration_revision,
                "service_image_path": request.service_image_path,
                "service_map_path": request.service_map_path,
            }
        else:
            stage = (
                "prepare_ram_image" if isinstance(request, PrepareRamImageRequest)
                else "prepare_advanced_flash_image" if isinstance(request, PrepareAdvancedFlashImageRequest)
                else "prepare_flash_image"
            )
            details = {
                "selection_revision": request.selection_revision,
                "source_path": request.source_path,
            }
        if failure.__cause__ is not None:
            details["exception_type"] = type(failure.__cause__).__name__
        error = GuiRuntimeError(
            failure.code,
            str(failure),
            stage,
            ErrorDisposition.SHOW_ONLY,
            task_id,
            True,
            details=details,
        )
        return TaskExecutionResult(
            task_id,
            TaskFinalStatus.FAILED,
            "Image preparation failed",
            str(failure),
            error=error,
        )

    @staticmethod
    def _validate_request(request: SerialConnectRequest) -> None:
        if not isinstance(request.port, str) or not request.port.strip():
            raise ValueError("port must not be empty")
        for name in ("baudrate", "tx_timeout_ms", "rx_timeout_ms", "autobaud_timeout_ms"):
            value = getattr(request, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def _make_connection_info(self, request: SerialConnectRequest, discovered) -> ConnectionInfo:
        info = discovered.device_info
        return ConnectionInfo(
            connection_id=uuid4().hex,
            transport_label="SCI / RS232",
            endpoint_label=request.port,
            connected_at=datetime.now(timezone.utc),
            target_key=discovered.target_key,
            details={
                "port": request.port,
                "baudrate": request.baudrate,
                "tx_timeout_ms": request.tx_timeout_ms,
                "rx_timeout_ms": request.rx_timeout_ms,
                "autobaud_timeout_ms": request.autobaud_timeout_ms,
                **asdict(info),
            },
        )

    @staticmethod
    def _publish(task_id, step_id, state, stage, message, progress) -> None:
        if progress is not None:
            progress(TaskProgressUpdate(task_id, step_id, state, stage, message))

    @staticmethod
    def _failure(
        task_id,
        code: str,
        message: str,
        stage: str = "connect",
        *,
        summary: str = "Connection failed",
        details: dict[str, object] | None = None,
        step_results: tuple[object, ...] = (),
    ) -> TaskExecutionResult:
        error = GuiRuntimeError(
            code,
            message,
            stage,
            ErrorDisposition.SHOW_ONLY,
            task_id,
            True,
            details=details or {},
        )
        return TaskExecutionResult(
            task_id,
            TaskFinalStatus.FAILED,
            summary,
            message,
            step_results=step_results,
            error=error,
        )


__all__ = ["RuntimeBackend"]
