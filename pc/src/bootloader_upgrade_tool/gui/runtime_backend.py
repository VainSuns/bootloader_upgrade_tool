"""Single-owner runtime backend for the Batch 12 SCI session."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
from threading import Lock
from typing import Any
from uuid import uuid4

from ..app_resources import AppResourceError, AppResourceProvider
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
    ImageIdentity,
    PreparedFlashImage,
    PreparedRamImage,
    PreparedServiceImage,
    prepare_flash_app_image,
    prepare_ram_app_image,
    prepare_service_image,
)
from ..images.models import RamImageIdentity
from ..image_workspace import ImageMaterializationWorkspace
from ..protocol.boot_protocol_client import ProtocolInfo
from ..protocol.models import DeviceInfo, ErrorDetail, MetadataSummary
from ..session import UpgradeSession, UpgradeSessionConfig
from ..targets import TargetProfile, target_profile_for_key
from ..transport import (
    TransportError,
    TransportOpenResult,
    TransportOpenStatus,
    TransportTimeoutError,
)
from ..transport.serial_transport import SerialTransport, SerialTransportConfig
from .connection_models import SerialConnectRequest, SerialDisconnectRequest
from .connection_command_executor import ConnectionCommandExecutor
from .connection_maintenance import (
    ConnectionMaintenanceScheduler,
    NoOpConnectionMaintenanceScheduler,
)
from .advanced_ram_models import (
    AdvancedRamOperationType,
    AdvancedRamOperationSnapshot,
    CheckAdvancedRamCrcRequest,
    LoadAdvancedRamImageRequest,
    PrepareRamImageRequest,
    PreparedRamImageSummary,
    RunAdvancedRamImageRequest,
)
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
    WriteAdvancedAppConfirmedRequest,
    WriteAdvancedBootAttemptRequest,
    WriteAdvancedImageValidRequest,
)
from .flash_service_models import (
    DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
    FlashServiceResourceState,
    FlashServiceResourceStatus,
    PrepareFlashServiceRequest,
    PreparedFlashServiceSummary,
)
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
    ConnectionRuntimeState,
    DataFreshness,
    DiagnosticGroup,
    EraseScope,
    FlashImageSummary,
    ImageParseStatus,
    RamCrcEvidence,
    RamImageSummary,
    RuntimeCpuId,
    RuntimeReadError,
    RuntimeStateStore,
    RuntimeV2Snapshot,
    TargetResourceState,
    VerifyEvidence,
)
from .runtime_v2_events import (
    ConnectionClosed,
    ConnectionOpened,
    DiagnosticReadFailed,
    DiagnosticReadSucceeded,
    MetadataReadFailed,
    MetadataReadSucceeded,
    MetadataWriteStarted,
    MemoryCleared,
    MemoryReadFailed,
    MemoryReadSucceeded,
    OperationStarted,
    OperationSucceeded,
    ProgramImageChanged,
    RamImageChanged,
    SectorSelectionChanged,
    SessionChanged,
    RuntimeOperationType,
)
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
ConnectionExecutorFactory = Callable[
    [UpgradeSession, ConnectionGeneration], ConnectionCommandExecutor
]


@dataclass(frozen=True, slots=True)
class ActiveTargetContext:
    cpu_id: RuntimeCpuId
    target_key: str
    connection: ConnectionRuntimeState
    profile: TargetProfile
    resource: TargetResourceState


class _ImagePreparationFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        image_path: str | None = None,
        map_path: str | None = None,
        commit_service_state: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.image_path = image_path
        self.map_path = map_path
        self.commit_service_state = commit_service_state


class _ProviderResourceFailure(AppResourceError):
    def __init__(self, code, message, image_path=None, map_path=None) -> None:
        super().__init__(message)
        self.code = code
        self.image_path = image_path
        self.map_path = map_path


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
        target_profile_resolver: Callable[[str], TargetProfile | None] = target_profile_for_key,
        prepare_ram_operation=prepare_ram_app_image,
        load_ram_operation=load_ram_image,
        check_ram_crc_operation=check_ram_crc,
        run_ram_operation=run_ram_image,
        erase_flash_image_area_operation=erase_flash_image_area,
        erase_sector_mask_operation=erase_sector_mask,
        program_flash_operation=program_flash_image,
        verify_flash_operation=verify_flash_image,
        prepare_flash_operation=prepare_flash_app_image,
        append_image_valid_operation=append_image_valid,
        append_boot_attempt_operation=append_boot_attempt,
        append_app_confirmed_operation=append_app_confirmed,
        app_resource_provider: AppResourceProvider | None = None,
        prepare_service_operation=prepare_service_image,
        connection_executor_factory: ConnectionExecutorFactory | None = None,
        maintenance_scheduler: ConnectionMaintenanceScheduler | None = None,
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
        self._connection_executor_factory = (
            connection_executor_factory
            if connection_executor_factory is not None
            else ConnectionCommandExecutor
        )
        self._maintenance_scheduler = (
            maintenance_scheduler
            if maintenance_scheduler is not None
            else NoOpConnectionMaintenanceScheduler()
        )
        self._connection_command_executor: ConnectionCommandExecutor | None = None
        self._pending_close: Any | None = None
        self._hex2000_executable_path = (
            str(hex2000_executable_path).strip() if hex2000_executable_path is not None else ""
        )
        self._global_settings_error = global_settings_error
        self._sci8_temp_dir = str(sci8_temp_dir).strip() if sci8_temp_dir is not None else ""
        self._program_image_revisions = {cpu_id: 0 for cpu_id in RuntimeCpuId}
        self._ram_image_revisions = {cpu_id: 0 for cpu_id in RuntimeCpuId}
        self._app_resource_provider: AppResourceProvider | None = None
        self._flash_service_resource_state = FlashServiceResourceState(
            0,
            "Unconfigured",
            None,
            None,
            FlashServiceResourceStatus.UNAVAILABLE,
            error_code="APP_RESOURCE_PROVIDER_REQUIRED",
            error_message="No AppResourceProvider is configured",
        )
        self._configuration_revision = 0
        self._device_info_operation = device_info_operation
        self._protocol_info_operation = protocol_info_operation
        self._last_error_operation = last_error_operation
        self._metadata_operation = metadata_operation
        self._target_profile_resolver = target_profile_resolver
        self._prepare_ram_operation = prepare_ram_operation
        self._load_ram_operation = load_ram_operation
        self._check_ram_crc_operation = check_ram_crc_operation
        self._run_ram_operation = run_ram_operation
        self._erase_flash_image_area_operation = erase_flash_image_area_operation
        self._erase_sector_mask_operation = erase_sector_mask_operation
        self._program_flash_operation = program_flash_operation
        self._verify_flash_operation = verify_flash_operation
        self._prepare_flash_operation = prepare_flash_operation
        self._append_image_valid_operation = append_image_valid_operation
        self._append_boot_attempt_operation = append_boot_attempt_operation
        self._append_app_confirmed_operation = append_app_confirmed_operation
        self._prepare_service_operation = prepare_service_operation
        if app_resource_provider is not None:
            self.configure_app_resource_provider(app_resource_provider)

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
    def connection_command_executor(self) -> ConnectionCommandExecutor | None:
        return self._connection_command_executor

    @property
    def active_target_context(self) -> ActiveTargetContext | None:
        runtime = self.runtime_v2_snapshot
        connection = runtime.connection
        info = self._connection_info
        profile = self._target
        device_info = self._device_info
        if connection is None or info is None or profile is None or device_info is None:
            return None
        try:
            cpu_id = RuntimeCpuId.from_target_key(info.target_key)
            profile_cpu_id = int(profile.cpu_id)
            device_cpu_id = int(device_info.cpu_id)
        except (TypeError, ValueError):
            return None
        resource = runtime.target_resources.get(cpu_id)
        if not (
            connection.connection_id == info.connection_id
            and connection.generation == runtime.connection_generation
            and connection.cpu_id is cpu_id
            and profile_cpu_id == device_cpu_id
            and cpu_id.value == f"cpu{profile_cpu_id}"
            and resource is not None
            and resource.cpu_id is cpu_id
        ):
            return None
        return ActiveTargetContext(cpu_id, info.target_key, connection, profile, resource)

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

    def record_memory_read_success(
        self,
        cpu_id: RuntimeCpuId,
        connection_generation: ConnectionGeneration,
        base_address: int,
        words: Sequence[int],
        read_at: datetime,
    ) -> RuntimeTransitionResult:
        return self._runtime_v2_dispatcher.dispatch(
            MemoryReadSucceeded(
                cpu_id, connection_generation, base_address, tuple(words), read_at
            )
        )

    def record_memory_read_failure(
        self,
        cpu_id: RuntimeCpuId,
        connection_generation: ConnectionGeneration,
        error: RuntimeReadError,
    ) -> RuntimeTransitionResult:
        return self._runtime_v2_dispatcher.dispatch(
            MemoryReadFailed(cpu_id, connection_generation, error)
        )

    def clear_memory(self, cpu_id: RuntimeCpuId) -> RuntimeTransitionResult:
        return self._runtime_v2_dispatcher.dispatch(MemoryCleared(cpu_id))

    def validate_erase_configuration(
        self,
        target_key: str,
        erase_scope: EraseScope,
        custom_sector_mask: int,
    ) -> None:
        RuntimeCpuId.from_target_key(target_key)
        if type(erase_scope) is not EraseScope:
            raise TypeError("erase_scope must be EraseScope")
        if type(custom_sector_mask) is not int or custom_sector_mask < 0:
            raise ValueError("custom_sector_mask must be a non-negative integer")
        profile = self._resolve_target_profile(target_key)
        flash = profile.memory_map.flash
        if flash is None:
            if custom_sector_mask:
                raise ValueError("target without Flash layout requires a zero custom mask")
            return
        if custom_sector_mask & flash.forbidden_erase_mask:
            raise ValueError("custom_sector_mask contains forbidden sectors")
        if custom_sector_mask & ~flash.allowed_erase_mask:
            raise ValueError("custom_sector_mask contains sectors outside the allowed erase mask")

    def set_erase_configuration(
        self,
        target_key: str,
        erase_scope: EraseScope,
        custom_sector_mask: int,
    ) -> RuntimeTransitionResult:
        self.validate_erase_configuration(target_key, erase_scope, custom_sector_mask)
        cpu_id = RuntimeCpuId.from_target_key(target_key)
        self._acquire()
        try:
            return self._runtime_v2_dispatcher.dispatch(
                SectorSelectionChanged(cpu_id, erase_scope, custom_sector_mask)
            )
        finally:
            self._lock.release()

    @property
    def pending_close(self) -> Any | None:
        return self._pending_close

    def ram_image_revision(self, target_key: str) -> int:
        cpu_id = RuntimeCpuId.from_target_key(target_key)
        with self._image_lock:
            return self._ram_image_revisions[cpu_id]

    def set_ram_image_path(self, target_key: str, path: str) -> int:
        if type(path) is not str:
            raise TypeError("path must be a string")
        cpu_id = RuntimeCpuId.from_target_key(target_key)
        self._acquire()
        try:
            with self._image_lock:
                previous_revision = self._ram_image_revisions[cpu_id]
                revision = previous_revision + 1
                self._ram_image_revisions[cpu_id] = revision
            try:
                self._runtime_v2_dispatcher.dispatch(
                    RamImageChanged(cpu_id, path, ImageParseStatus.EMPTY)
                )
            except Exception:
                with self._image_lock:
                    self._ram_image_revisions[cpu_id] = previous_revision
                raise
            return revision
        finally:
            self._lock.release()

    def begin_ram_image_parse(
        self, target_key: str, source_path: str, selection_revision: int
    ) -> RuntimeTransitionResult:
        self._acquire()
        try:
            return self._begin_ram_image_parse(
                RuntimeCpuId.from_target_key(target_key), source_path, selection_revision
            )
        finally:
            self._lock.release()

    def fail_ram_image_parse(
        self,
        target_key: str,
        source_path: str,
        selection_revision: int,
        code: str,
        message: str,
    ) -> RuntimeTransitionResult | None:
        self._acquire()
        try:
            return self._fail_ram_image_parse(
                RuntimeCpuId.from_target_key(target_key),
                source_path,
                selection_revision,
                code,
                message,
            )
        finally:
            self._lock.release()

    def _begin_ram_image_parse(
        self, cpu_id: RuntimeCpuId, source_path: str, selection_revision: int
    ) -> RuntimeTransitionResult:
        path = self._normalized_ram_path(source_path)
        resource = self.target_resources[cpu_id]
        try:
            current_path = self._normalized_ram_path(resource.ram_image_path)
        except (OSError, RuntimeError, ValueError):
            raise RuntimeError("RAM image selection changed") from None
        with self._image_lock:
            current_revision = self._ram_image_revisions[cpu_id]
        if type(selection_revision) is not int or selection_revision != current_revision or path != current_path:
            raise RuntimeError("RAM image selection changed")
        return self._runtime_v2_dispatcher.dispatch(
            RamImageChanged(cpu_id, resource.ram_image_path, ImageParseStatus.PARSING)
        )

    def _fail_ram_image_parse(
        self,
        cpu_id: RuntimeCpuId,
        source_path: str,
        selection_revision: int,
        code: str,
        message: str,
    ) -> RuntimeTransitionResult | None:
        if type(code) is not str or not code or type(message) is not str or not message:
            raise ValueError("code and message must be non-empty strings")
        try:
            path = self._normalized_ram_path(source_path)
            resource = self.target_resources[cpu_id]
            current_path = self._normalized_ram_path(resource.ram_image_path)
        except (OSError, RuntimeError, ValueError):
            return None
        with self._image_lock:
            current_revision = self._ram_image_revisions[cpu_id]
        if type(selection_revision) is not int or selection_revision != current_revision or path != current_path:
            return None
        return self._runtime_v2_dispatcher.dispatch(
            RamImageChanged(
                cpu_id,
                resource.ram_image_path,
                ImageParseStatus.ERROR,
                parse_error=f"Code: {code}\n{message}",
            )
        )

    @staticmethod
    def _normalized_ram_path(path: str) -> str:
        if type(path) is not str or not path.strip():
            raise ValueError("RAM image path must not be empty")
        return str(Path(path.strip()).expanduser().resolve(strict=False))

    def advanced_flash_selection_revision(self, target_key: str) -> int:
        return self.program_image_revision(target_key)

    def program_image_revision(self, target_key: str) -> int:
        cpu_id = RuntimeCpuId.from_target_key(target_key)
        with self._image_lock:
            return self._program_image_revisions[cpu_id]

    def set_program_image_path(self, target_key: str, path: str) -> int:
        if type(path) is not str:
            raise TypeError("path must be a string")
        cpu_id = RuntimeCpuId.from_target_key(target_key)
        self._acquire()
        try:
            with self._image_lock:
                previous_revision = self._program_image_revisions[cpu_id]
                revision = previous_revision + 1
                self._program_image_revisions[cpu_id] = revision
            try:
                self._runtime_v2_dispatcher.dispatch(
                    ProgramImageChanged(cpu_id, path, ImageParseStatus.EMPTY)
                )
            except Exception:
                with self._image_lock:
                    self._program_image_revisions[cpu_id] = previous_revision
                raise
            return revision
        finally:
            self._lock.release()

    def begin_program_image_parse(
        self, target_key: str, source_path: str, selection_revision: int
    ) -> RuntimeTransitionResult:
        self._acquire()
        try:
            return self._begin_program_image_parse(
                RuntimeCpuId.from_target_key(target_key), source_path, selection_revision
            )
        finally:
            self._lock.release()

    def fail_program_image_parse(
        self,
        target_key: str,
        source_path: str,
        selection_revision: int,
        code: str,
        message: str,
    ) -> RuntimeTransitionResult | None:
        self._acquire()
        try:
            return self._fail_program_image_parse(
                RuntimeCpuId.from_target_key(target_key),
                source_path,
                selection_revision,
                code,
                message,
            )
        finally:
            self._lock.release()

    def _begin_program_image_parse(
        self, cpu_id: RuntimeCpuId, source_path: str, selection_revision: int
    ) -> RuntimeTransitionResult:
        path = self._normalized_program_path(source_path)
        resource = self.runtime_v2_snapshot.target_resources[cpu_id]
        try:
            current_path = self._normalized_program_path(resource.program_image_path)
        except (OSError, RuntimeError, ValueError):
            raise RuntimeError("Program image selection changed") from None
        with self._image_lock:
            current_revision = self._program_image_revisions[cpu_id]
        if (
            type(selection_revision) is not int
            or isinstance(selection_revision, bool)
            or selection_revision != current_revision
            or path != current_path
        ):
            raise RuntimeError("Program image selection changed")
        return self._runtime_v2_dispatcher.dispatch(
            ProgramImageChanged(
                cpu_id, resource.program_image_path, ImageParseStatus.PARSING
            )
        )

    def _fail_program_image_parse(
        self,
        cpu_id: RuntimeCpuId,
        source_path: str,
        selection_revision: int,
        code: str,
        message: str,
    ) -> RuntimeTransitionResult | None:
        if type(code) is not str or not code or type(message) is not str or not message:
            raise ValueError("code and message must be non-empty strings")
        try:
            path = self._normalized_program_path(source_path)
        except (OSError, RuntimeError, ValueError):
            return None
        resource = self.runtime_v2_snapshot.target_resources[cpu_id]
        try:
            current_path = self._normalized_program_path(resource.program_image_path)
        except (OSError, RuntimeError, ValueError):
            return None
        with self._image_lock:
            current_revision = self._program_image_revisions[cpu_id]
        if (
            type(selection_revision) is not int
            or isinstance(selection_revision, bool)
            or selection_revision != current_revision
            or path != current_path
        ):
            return None
        return self._runtime_v2_dispatcher.dispatch(
            ProgramImageChanged(
                cpu_id,
                resource.program_image_path,
                ImageParseStatus.ERROR,
                parse_error=f"Code: {code}\n{message}",
            )
        )

    @staticmethod
    def _normalized_program_path(path: str) -> str:
        if type(path) is not str or not path.strip():
            raise ValueError("Image path must not be empty")
        return str(Path(path.strip()).expanduser().resolve(strict=False))

    @property
    def app_resource_provider(self) -> AppResourceProvider | None:
        return self._app_resource_provider

    @property
    def flash_service_resource_state(self) -> FlashServiceResourceState:
        with self._image_lock:
            return self._flash_service_resource_state

    @property
    def service_configuration_revision(self) -> int:
        return self.flash_service_resource_state.revision

    def configure_app_resource_provider(self, provider: AppResourceProvider) -> None:
        if not isinstance(provider, AppResourceProvider):
            raise TypeError("provider must implement AppResourceProvider")
        self._acquire()
        try:
            if self._app_resource_provider is provider:
                return
            if self._app_resource_provider is not None:
                raise RuntimeError("RuntimeBackend AppResourceProvider cannot be replaced")
            self._app_resource_provider = provider
            with self._image_lock:
                previous = self._flash_service_resource_state
                self._flash_service_resource_state = replace(
                    previous,
                    revision=previous.revision + 1,
                    provider_name=type(provider).__name__,
                )
            self._refresh_flash_service_resources_locked()
        finally:
            self._lock.release()

    def refresh_flash_service_resources(self) -> FlashServiceResourceState:
        self._acquire()
        try:
            return self._refresh_flash_service_resources_locked()
        finally:
            self._lock.release()

    def _refresh_flash_service_resources_locked(self) -> FlashServiceResourceState:
        previous = self.flash_service_resource_state
        provider = self._app_resource_provider
        if provider is None:
            state = FlashServiceResourceState(
                previous.revision,
                "Unconfigured",
                None,
                None,
                FlashServiceResourceStatus.UNAVAILABLE,
                error_code="APP_RESOURCE_PROVIDER_REQUIRED",
                error_message="No AppResourceProvider is configured",
            )
        else:
            try:
                image_path, map_path = self._resolve_service_resource_paths(provider)
            except AppResourceError as exc:
                image_path = getattr(exc, "image_path", None) or previous.image_path
                map_path = getattr(exc, "map_path", None) or previous.map_path
                changed = (
                    previous.status is not FlashServiceResourceStatus.UNAVAILABLE
                    or previous.provider_name != type(provider).__name__
                    or (previous.image_path, previous.map_path) != (image_path, map_path)
                )
                state = FlashServiceResourceState(
                    previous.revision + int(changed),
                    type(provider).__name__,
                    image_path,
                    map_path,
                    FlashServiceResourceStatus.UNAVAILABLE,
                    error_code=getattr(exc, "code", type(exc).__name__),
                    error_message=str(exc),
                )
            else:
                paths = (str(image_path), str(map_path))
                unchanged = (
                    previous.provider_name == type(provider).__name__
                    and (previous.image_path, previous.map_path) == paths
                )
                if unchanged and previous.status is FlashServiceResourceStatus.READY:
                    return previous
                state = FlashServiceResourceState(
                    previous.revision + int(not unchanged or previous.status is FlashServiceResourceStatus.UNAVAILABLE),
                    type(provider).__name__,
                    *paths,
                    FlashServiceResourceStatus.UNVALIDATED,
                )
        with self._image_lock:
            self._flash_service_resource_state = state
        return state

    @staticmethod
    def _resolve_service_resource_paths(provider: AppResourceProvider) -> tuple[Path, Path]:
        values = []
        failures = []
        for method in (
            provider.flash_service_image_path,
            provider.flash_service_map_path,
        ):
            try:
                value = method()
                if not isinstance(value, Path):
                    raise AppResourceError("AppResourceProvider paths must be Path values")
                values.append(value.expanduser().resolve(strict=False))
                failures.append(None)
            except AppResourceError as exc:
                values.append(None)
                failures.append(exc)
            except Exception as exc:
                values.append(None)
                failures.append(AppResourceError(f"AppResourceProvider failed: {exc}"))
        if any(failures):
            failure = next(item for item in failures if item is not None)
            raise _ProviderResourceFailure(
                type(failure).__name__,
                str(failure),
                str(values[0]) if values[0] is not None else None,
                str(values[1]) if values[1] is not None else None,
            ) from failure
        image_path, map_path = values
        if image_path == map_path:
            raise AppResourceError("Flash Service image and map paths must differ")
        return image_path, map_path

    @property
    def metadata_status_snapshot(self) -> MetadataStatusSnapshot | None:
        value = self.runtime_v2_snapshot.metadata_state.value
        return value if isinstance(value, MetadataStatusSnapshot) else None

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
        with self._lock:
            hex_path = hex2000_executable_path.strip()
            temp_dir = sci8_temp_dir.strip()
            if (hex_path, temp_dir) == (self._hex2000_executable_path, self._sci8_temp_dir):
                return
            self._hex2000_executable_path = hex_path
            self._sci8_temp_dir = temp_dir
            self._global_settings_error = None
            snapshot = self.runtime_v2_snapshot
            source_suffixes = {
                cpu_id: self._program_source_suffix(resource.program_image_path)
                for cpu_id, resource in snapshot.target_resources.items()
            }
            ram_source_suffixes = {
                cpu_id: self._program_source_suffix(resource.ram_image_path)
                for cpu_id, resource in snapshot.target_resources.items()
            }
            with self._image_lock:
                self._configuration_revision += 1
                configuration_revision = self._configuration_revision
                for cpu_id, resource in snapshot.target_resources.items():
                    if source_suffixes[cpu_id] == ".out":
                        self._program_image_revisions[cpu_id] += 1
                    if ram_source_suffixes[cpu_id] == ".out":
                        self._ram_image_revisions[cpu_id] += 1
                service_state = self._flash_service_resource_state
                if (
                    service_state.status is not FlashServiceResourceStatus.UNAVAILABLE
                    and service_state.image_path is not None
                    and service_state.map_path is not None
                ):
                    self._flash_service_resource_state = FlashServiceResourceState(
                        service_state.revision + 1,
                        service_state.provider_name,
                        service_state.image_path,
                        service_state.map_path,
                        FlashServiceResourceStatus.UNVALIDATED,
                    )
            for cpu_id, resource in snapshot.target_resources.items():
                if source_suffixes[cpu_id] == ".out":
                    self._runtime_v2_dispatcher.dispatch(
                        ProgramImageChanged(
                            cpu_id, resource.program_image_path, ImageParseStatus.EMPTY
                        )
                    )
                if ram_source_suffixes[cpu_id] == ".out":
                    self._runtime_v2_dispatcher.dispatch(
                        RamImageChanged(
                            cpu_id, resource.ram_image_path, ImageParseStatus.EMPTY
                        )
                    )

    @staticmethod
    def _program_source_suffix(path: str) -> str:
        if type(path) is not str:
            raise TypeError("path must be a string")
        trimmed = path.strip()
        return Path(trimmed).suffix.lower() if trimmed else ""

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
                self._program_image_revisions = {cpu_id: 0 for cpu_id in RuntimeCpuId}
                self._ram_image_revisions = {cpu_id: 0 for cpu_id in RuntimeCpuId}
            return result
        finally:
            self._lock.release()

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
                self._fail_ram_image_parse(
                    RuntimeCpuId.from_target_key(request.target_key),
                    request.source_path,
                    request.selection_revision,
                    exc.code,
                    str(exc) or exc.code,
                )
            elif isinstance(request, PrepareFlashServiceRequest):
                if exc.commit_service_state:
                    self._set_service_failure_state(exc, request.resource_revision)
            else:
                self._fail_program_image_parse(
                    RuntimeCpuId.from_target_key(request.target_key),
                    request.source_path,
                    request.selection_revision,
                    exc.code,
                    str(exc) or exc.code,
                )
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
                self._dispatch_metadata_failure(captured, self._read_error(result))
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
            self._runtime_v2_dispatcher.dispatch(
                MetadataReadSucceeded(
                    RuntimeCpuId.from_target_key(captured[3]),
                    captured[4],
                    normalized_snapshot,
                )
            )
            return final_result
        except Exception as exc:
            self._dispatch_metadata_failure(
                captured,
                RuntimeReadError(type(exc).__name__, str(exc) or type(exc).__name__, "GET_METADATA_SUMMARY"),
            )
            raise

    def _read_device_info_status(self, task_id, request: DeviceInfoRequest, progress) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None:
            return self._stale_status_failure(task_id)
        failure_dispatched = False
        try:
            result = self._call_status_operation(
                task_id, request, "GET_DEVICE_INFO", self._device_info_operation, captured, progress
            )
            if not isinstance(result, OperationResult):
                raise TypeError("status operation returned an invalid result")
            if self._status_connection(request.connection_id, captured) is None:
                return self._stale_status_failure(task_id, result)
            if not result.ok:
                failure_dispatched = True
                self._dispatch_diagnostic_failure(
                    captured, DiagnosticGroup.DEVICE_INFO, self._read_error(result)
                )
                return self._status_operation_failure(task_id, result)

            info = DeviceInfo(**dict(result.summary))
            discovered = self._device_info
            if discovered is None:
                raise RuntimeError("connected target is missing discovery DeviceInfo")
            if (info.device_id, info.cpu_id) != (discovered.device_id, discovered.cpu_id):
                failure_dispatched = True
                self._dispatch_diagnostic_failure(
                    captured,
                    DiagnosticGroup.DEVICE_INFO,
                    RuntimeReadError(
                        "TARGET_MISMATCH",
                        "DeviceInfo changed from the connected target identity",
                        result.stage,
                    ),
                )
                return self._target_mismatch_failure(task_id, result, discovered, info)
            snapshot = DeviceInfoStatusSnapshot(request.connection_id, captured[3], result, info)
            self._complete_status_step(task_id, request, result, progress)
            final_result = self._status_success(task_id, result, snapshot)
            if self._status_connection(request.connection_id, captured) is None:
                return self._stale_status_failure(task_id, result)
            self._device_info = info
            self._runtime_v2_dispatcher.dispatch(
                DiagnosticReadSucceeded(
                    RuntimeCpuId.from_target_key(captured[3]),
                    captured[4],
                    DiagnosticGroup.DEVICE_INFO,
                    final_result.payload,
                )
            )
            return final_result
        except Exception as exc:
            if not failure_dispatched:
                self._dispatch_diagnostic_failure(
                    captured,
                    DiagnosticGroup.DEVICE_INFO,
                    RuntimeReadError(
                        type(exc).__name__, str(exc) or type(exc).__name__, "GET_DEVICE_INFO"
                    ),
                )
            raise

    def _read_protocol_info_status(self, task_id, request: ProtocolInfoRequest, progress) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None:
            return self._stale_status_failure(task_id)
        failure_dispatched = False
        try:
            result = self._call_status_operation(
                task_id, request, "GET_PROTOCOL_INFO", self._protocol_info_operation, captured, progress
            )
            if not isinstance(result, OperationResult):
                raise TypeError("status operation returned an invalid result")
            if self._status_connection(request.connection_id, captured) is None:
                return self._stale_status_failure(task_id, result)
            if not result.ok:
                failure_dispatched = True
                self._dispatch_diagnostic_failure(
                    captured, DiagnosticGroup.PROTOCOL_INFO, self._read_error(result)
                )
                return self._status_operation_failure(task_id, result)
            snapshot = ProtocolInfoStatusSnapshot(
                request.connection_id, captured[3], result, ProtocolInfo(**dict(result.summary))
            )
            self._complete_status_step(task_id, request, result, progress)
            final_result = self._status_success(task_id, result, snapshot)
            if self._status_connection(request.connection_id, captured) is None:
                return self._stale_status_failure(task_id, result)
            self._runtime_v2_dispatcher.dispatch(
                DiagnosticReadSucceeded(
                    RuntimeCpuId.from_target_key(captured[3]),
                    captured[4],
                    DiagnosticGroup.PROTOCOL_INFO,
                    final_result.payload,
                )
            )
            return final_result
        except Exception as exc:
            if not failure_dispatched:
                self._dispatch_diagnostic_failure(
                    captured,
                    DiagnosticGroup.PROTOCOL_INFO,
                    RuntimeReadError(
                        type(exc).__name__, str(exc) or type(exc).__name__, "GET_PROTOCOL_INFO"
                    ),
                )
            raise

    def _read_last_error_status(self, task_id, request: LastErrorRequest, progress) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None:
            return self._stale_status_failure(task_id)
        failure_dispatched = False
        try:
            result = self._call_status_operation(
                task_id, request, "GET_LAST_ERROR", self._last_error_operation, captured, progress
            )
            if not isinstance(result, OperationResult):
                raise TypeError("status operation returned an invalid result")
            if self._status_connection(request.connection_id, captured) is None:
                return self._stale_status_failure(task_id, result)
            if not result.ok:
                failure_dispatched = True
                self._dispatch_diagnostic_failure(
                    captured, DiagnosticGroup.LAST_ERROR, self._read_error(result)
                )
                return self._status_operation_failure(task_id, result)
            snapshot = LastErrorStatusSnapshot(
                request.connection_id, captured[3], result, ErrorDetail(**dict(result.summary))
            )
            self._complete_status_step(task_id, request, result, progress)
            final_result = self._status_success(task_id, result, snapshot)
            if self._status_connection(request.connection_id, captured) is None:
                return self._stale_status_failure(task_id, result)
            self._runtime_v2_dispatcher.dispatch(
                DiagnosticReadSucceeded(
                    RuntimeCpuId.from_target_key(captured[3]),
                    captured[4],
                    DiagnosticGroup.LAST_ERROR,
                    final_result.payload,
                )
            )
            return final_result
        except Exception as exc:
            if not failure_dispatched:
                self._dispatch_diagnostic_failure(
                    captured,
                    DiagnosticGroup.LAST_ERROR,
                    RuntimeReadError(
                        type(exc).__name__, str(exc) or type(exc).__name__, "GET_LAST_ERROR"
                    ),
                )
            raise

    def _status_connection(self, connection_id: str, expected=None):
        context = self.active_target_context
        if (
            self._session is None
            or context is None
            or context.connection.connection_id != connection_id
        ):
            return None
        current = (
            self._session,
            context.profile,
            context.connection.connection_id,
            context.target_key,
            context.connection.generation,
        )
        if expected is not None and (
            current[0] is not expected[0]
            or current[1] is not expected[1]
            or current[2:] != expected[2:]
        ):
            return None
        return current

    @staticmethod
    def _read_error(result: OperationResult) -> RuntimeReadError:
        error = result.error
        if error is None:
            return RuntimeReadError("READ_FAILED", result.stage, result.stage)
        return RuntimeReadError(error.code, error.message, error.stage)

    def _dispatch_metadata_failure(self, captured, error: RuntimeReadError) -> None:
        if self._status_connection(captured[2], captured) is not None:
            self._runtime_v2_dispatcher.dispatch(
                MetadataReadFailed(
                    RuntimeCpuId.from_target_key(captured[3]), captured[4], error
                )
            )

    def _dispatch_diagnostic_failure(
        self, captured, group: DiagnosticGroup, error: RuntimeReadError
    ) -> None:
        if self._status_connection(captured[2], captured) is not None:
            self._runtime_v2_dispatcher.dispatch(
                DiagnosticReadFailed(
                    RuntimeCpuId.from_target_key(captured[3]), captured[4], group, error
                )
            )

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
        try:
            cpu_id = RuntimeCpuId.from_target_key(target_key)
        except (TypeError, ValueError):
            return LoadedImageMatch.NO_PREPARED_IMAGE
        resource = self.runtime_v2_snapshot.target_resources.get(cpu_id)
        if resource is None or resource.cpu_id is not cpu_id or resource.program_image_summary is None:
            return LoadedImageMatch.NO_PREPARED_IMAGE
        identity = resource.program_image_summary.identity
        matches = (
            identity.entry_point == raw.entry_point
            and identity.image_size_words == raw.image_size_words
            and identity.image_crc32 == raw.image_crc32
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
            self._release_connection_executor()
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
            self._session = session
            self._transport = transport
            self._target = discovered.target_profile
            self._device_info = discovered.device_info
            self._connection_info = connection_info
            transition = self._runtime_v2_dispatcher.dispatch(ConnectionOpened(connection_info))
            generation = transition.snapshot.connection_generation
            # Stage 6B moves all connected GUI Runtime operations through execute_foreground().
            self._connection_command_executor = self._connection_executor_factory(
                session, generation
            )
            self._maintenance_scheduler.connection_opened(generation)
            return result
        except Exception:
            self._clear_active()
            self._cleanup_partial(session, transport)
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
        self._publish(task_id, step_id, TaskStepState.STARTED, step_id.upper(), title, progress)
        resource = self._session or self._transport or self._pending_close
        self._pending_close = resource
        if resource is None:
            self._clear_active()
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
        self._clear_active()
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
        self._release_connection_executor()
        connection = self._runtime_v2_store.snapshot().connection
        if connection is not None:
            self._runtime_v2_dispatcher.dispatch(
                ConnectionClosed(connection.connection_id, connection.generation)
            )
        self._session = None
        self._transport = None
        self._target = None
        self._device_info = None
        self._connection_info = None

    def _release_connection_executor(self) -> None:
        executor = self._connection_command_executor
        if executor is None:
            return
        was_valid = executor.is_valid
        generation = executor.generation
        executor.invalidate()
        self._connection_command_executor = None
        if was_valid:
            self._maintenance_scheduler.connection_closed(generation)

    def _prepare_flash_image(self, task_id, request: PrepareFlashImageRequest, progress) -> TaskExecutionResult:
        cpu_id = RuntimeCpuId.from_target_key(request.target_key)
        resource = self.runtime_v2_snapshot.target_resources[cpu_id]
        try:
            request_path = self._normalized_program_path(request.source_path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise _ImagePreparationFailure("INVALID_IMAGE_PATH", str(exc)) from exc
        if (
            resource.program_image_parse_status is ImageParseStatus.EMPTY
            and not resource.program_image_path
        ):
            with self._image_lock:
                if self._program_image_revisions[cpu_id] != 0:
                    raise _ImagePreparationFailure(
                        "IMAGE_SELECTION_CHANGED", "The selected image changed before preparation started"
                    )
                self._program_image_revisions[cpu_id] = request.selection_revision
            self._runtime_v2_dispatcher.dispatch(
                ProgramImageChanged(
                    cpu_id, request.source_path, ImageParseStatus.PARSING
                )
            )
            resource = self.runtime_v2_snapshot.target_resources[cpu_id]
        current_path = self._normalized_program_path(resource.program_image_path)
        with self._image_lock:
            current_revision = self._program_image_revisions[cpu_id]
        if request.selection_revision != current_revision or request_path != current_path:
            raise _ImagePreparationFailure(
                "IMAGE_SELECTION_CHANGED",
                "The selected image changed before preparation started",
            )
        if resource.program_image_parse_status is not ImageParseStatus.PARSING:
            self._begin_program_image_parse(cpu_id, request_path, request.selection_revision)
        target_label = request.target_key.upper()
        self._publish(
            task_id,
            "prepare_flash_image",
            TaskStepState.STARTED,
            "PREPARE_FLASH_IMAGE",
            f"Preparing {target_label} App image",
            progress,
        )
        target_profile = self._resolve_target_profile(request.target_key)
        prepared, after, source_kind, hex2000_source, hex2000_executable = (
            self._materialize_flash_app(
                target_key=request.target_key,
                target_profile=target_profile,
                source_path=request.source_path,
                expected_identity=None,
                expected_effective_sector_mask=None,
            )
        )
        summary = self._build_image_summary(
            request,
            prepared,
            source_kind,
            after,
            hex2000_source,
            Path(hex2000_executable) if hex2000_executable else None,
        )
        self._publish(
            task_id,
            "prepare_flash_image",
            TaskStepState.COMPLETED,
            "PREPARE_FLASH_IMAGE",
            f"{target_label} App image prepared",
            progress,
        )
        result = TaskExecutionResult(
            task_id,
            TaskFinalStatus.SUCCEEDED,
            "Image prepared",
            f"{target_label} App image prepared",
            payload=summary,
        )
        current = self.runtime_v2_snapshot.target_resources[cpu_id]
        with self._image_lock:
            current_revision = self._program_image_revisions[cpu_id]
        if (
            request.selection_revision != current_revision
            or request_path != self._normalized_program_path(current.program_image_path)
        ):
            raise _ImagePreparationFailure(
                "IMAGE_SELECTION_CHANGED", "The selected image changed during preparation"
            )
        self._runtime_v2_dispatcher.dispatch(
            ProgramImageChanged(
                cpu_id,
                current.program_image_path,
                ImageParseStatus.READY,
                FlashImageSummary(prepared.identity, prepared.sector_mask),
            )
        )
        return result

    def _prepare_ram_image(self, task_id, request: PrepareRamImageRequest, progress) -> TaskExecutionResult:
        cpu_id = RuntimeCpuId.from_target_key(request.target_key)
        try:
            request_path = self._normalized_ram_path(request.source_path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise _ImagePreparationFailure("INVALID_IMAGE_PATH", str(exc)) from exc
        resource = self.target_resources[cpu_id]
        with self._image_lock:
            revision = self._ram_image_revisions[cpu_id]
        if (
            revision == 0
            and request.selection_revision == 0
            and resource.ram_image_parse_status is ImageParseStatus.EMPTY
            and not resource.ram_image_path
        ):
            self._runtime_v2_dispatcher.dispatch(
                RamImageChanged(cpu_id, request.source_path, ImageParseStatus.PARSING)
            )
            resource = self.target_resources[cpu_id]
        try:
            current_path = self._normalized_ram_path(resource.ram_image_path)
        except (OSError, RuntimeError, ValueError):
            current_path = ""
        if (
            request.selection_revision != revision
            or request_path != current_path
            or resource.ram_image_parse_status is not ImageParseStatus.PARSING
        ):
            raise _ImagePreparationFailure("IMAGE_SELECTION_CHANGED", "The RAM image selection changed")
        self._publish(task_id, "prepare_ram_image", TaskStepState.STARTED, "PREPARE_RAM_IMAGE", "Preparing RAM image", progress)
        target_profile = self._resolve_target_profile(request.target_key)
        prepared, after, source_kind, executable_source, executable = (
            self._materialize_ram_app(
                target_key=request.target_key,
                source_path=request.source_path,
                expected_identity=None,
                target_profile=target_profile,
            )
        )
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
            executable,
        )
        canonical_summary = RamImageSummary(
            RamImageIdentity(prepared.entry_point, prepared.total_words, prepared.image_crc32)
        )
        self._publish(task_id, "prepare_ram_image", TaskStepState.COMPLETED, "PREPARE_RAM_IMAGE", "RAM image prepared", progress)
        current = self.target_resources[cpu_id]
        try:
            current_path = self._normalized_ram_path(current.ram_image_path)
        except (OSError, RuntimeError, ValueError):
            current_path = ""
        with self._image_lock:
            if (
                request.selection_revision != self._ram_image_revisions[cpu_id]
                or request_path != current_path
            ):
                raise _ImagePreparationFailure("IMAGE_SELECTION_CHANGED", "The RAM image selection changed during preparation")
        self._runtime_v2_dispatcher.dispatch(
            RamImageChanged(
                cpu_id,
                current.ram_image_path,
                ImageParseStatus.READY,
                canonical_summary,
            )
        )
        return TaskExecutionResult(task_id, TaskFinalStatus.SUCCEEDED, "RAM image prepared", "RAM image prepared", payload=summary)

    def _prepare_flash_service(
        self, task_id, request: PrepareFlashServiceRequest, progress
    ) -> TaskExecutionResult:
        state = self.flash_service_resource_state
        if (
            request.resource_revision != state.revision
            or request.tool_configuration_revision != self._configuration_revision
        ):
            raise _ImagePreparationFailure(
                "SERVICE_CONFIGURATION_CHANGED",
                "The Flash Service inputs changed",
                commit_service_state=False,
            )
        if state.image_path is None or state.map_path is None:
            raise _ImagePreparationFailure(
                state.error_code or "APP_RESOURCE_PROVIDER_REQUIRED",
                state.error_message or "Flash Service resources are unavailable",
                image_path=state.image_path,
                map_path=state.map_path,
            )
        target_key = request.target_key
        target_profile = self._resolve_target_profile(target_key)
        target_label = target_key.upper()
        self._publish(
            task_id, "prepare_flash_service", TaskStepState.STARTED,
            "PREPARE_FLASH_SERVICE", f"Preparing {target_label} Flash Service", progress,
        )
        with self._image_lock:
            self._flash_service_resource_state = FlashServiceResourceState(
                state.revision,
                state.provider_name,
                state.image_path,
                state.map_path,
                FlashServiceResourceStatus.UNVALIDATED,
            )
        _prepared, summary = self._materialize_flash_service(
            target_key=target_key,
            target_profile=target_profile,
            expected_state=None,
        )
        if (
            summary.provider_name != state.provider_name
            or summary.service_image_path != state.image_path
            or summary.service_map_path != state.map_path
        ):
            raise _ImagePreparationFailure(
                "SERVICE_RESOURCE_CHANGED",
                "Flash Service provider paths changed during validation",
                image_path=summary.service_image_path,
                map_path=summary.service_map_path,
            )
        result_revision = state.revision
        if state.summary is not None and not self._service_identity_matches(state.summary, summary):
            result_revision += 1
            summary = replace(summary, resource_revision=result_revision)
        with self._image_lock:
            if (
                request.resource_revision != self._flash_service_resource_state.revision
                or request.tool_configuration_revision != self._configuration_revision
            ):
                raise _ImagePreparationFailure("SERVICE_CONFIGURATION_CHANGED", "The Flash Service inputs changed during preparation")
            self._flash_service_resource_state = FlashServiceResourceState(
                result_revision,
                summary.provider_name,
                summary.service_image_path,
                summary.service_map_path,
                FlashServiceResourceStatus.READY,
                summary,
            )
        self._publish(
            task_id, "prepare_flash_service", TaskStepState.COMPLETED,
            "PREPARE_FLASH_SERVICE", f"{target_label} Flash Service prepared", progress,
        )
        return TaskExecutionResult(
            task_id, TaskFinalStatus.SUCCEEDED, f"{target_label} Flash Service prepared",
            f"{target_label} Flash Service prepared", payload=summary,
        )

    def _materialize_flash_service(
        self,
        *,
        target_key: str,
        target_profile: TargetProfile,
        expected_state: FlashServiceResourceState | None,
    ) -> tuple[PreparedServiceImage, PreparedFlashServiceSummary]:
        target = self._validate_target_profile(target_key, target_profile)
        provider = self._app_resource_provider
        if provider is None:
            raise _ImagePreparationFailure(
                "APP_RESOURCE_PROVIDER_REQUIRED", "No AppResourceProvider is configured"
            )
        try:
            image_path, map_path = self._resolve_service_resource_paths(provider)
        except AppResourceError as exc:
            raise _ImagePreparationFailure(
                getattr(exc, "code", type(exc).__name__),
                str(exc),
                image_path=getattr(exc, "image_path", None),
                map_path=getattr(exc, "map_path", None),
            ) from exc
        source_kind = self._source_kind(image_path)
        image_before = self._fingerprint(image_path)
        map_before = self._fingerprint(map_path)
        executable = None
        executable_source = Hex2000Source.NOT_USED
        if source_kind is ImageSourceKind.OUT:
            if self._global_settings_error is not None:
                raise _ImagePreparationFailure("GLOBAL_SETTINGS_LOAD_FAILED", self._global_settings_error)
            try:
                executable = locate_hex2000(
                    self._hex2000_executable_path or None, environ=os.environ
                )
            except Hex2000ConfigurationError as exc:
                raise _ImagePreparationFailure("HEX2000_CONFIGURATION_INVALID", str(exc)) from exc
            except Hex2000NotFoundError as exc:
                raise _ImagePreparationFailure("HEX2000_NOT_FOUND", str(exc)) from exc
            executable_source = (
                Hex2000Source.GLOBAL_SETTINGS
                if self._hex2000_executable_path
                else Hex2000Source.C2000_CG_ROOT
            )
        try:
            prepared = self._prepare_service_operation(
                image_path,
                map_path,
                target=target,
                descriptor_symbol=DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
                hex2000=str(executable) if executable else None,
                work_dir=self._sci8_temp_dir or None,
            )
        except Sci8ParseError as exc:
            raise _ImagePreparationFailure("IMAGE_PARSE_FAILED", str(exc)) from exc
        except Hex2000Error as exc:
            raise _ImagePreparationFailure("IMAGE_CONVERSION_FAILED", str(exc)) from exc
        except (FileNotFoundError, OSError) as exc:
            raise _ImagePreparationFailure("SERVICE_FILE_ACCESS_FAILED", str(exc)) from exc
        except ValueError as exc:
            raise _ImagePreparationFailure("SERVICE_VALIDATION_FAILED", str(exc)) from exc
        if type(prepared) is not PreparedServiceImage:
            raise TypeError("Flash Service preparation returned an invalid result")
        image_after = self._fingerprint(image_path, during_preparation=True)
        map_after = self._fingerprint(map_path, during_preparation=True)
        if image_before != image_after or map_before != map_after:
            raise _ImagePreparationFailure(
                "SERVICE_CHANGED_DURING_PREPARATION",
                "A Flash Service input changed during preparation",
            )
        revision = expected_state.revision if expected_state is not None else self.service_configuration_revision
        summary = PreparedFlashServiceSummary(
            target_key,
            type(provider).__name__,
            image_after.resolved_path,
            map_after.resolved_path,
            DEFAULT_SERVICE_DESCRIPTOR_SYMBOL,
            revision,
            self._configuration_revision,
            source_kind,
            image_after,
            map_after,
            prepared.descriptor_address,
            prepared.api_table_address,
            prepared.crc_patch_address,
            prepared.total_words,
            prepared.expected_crc32,
            prepared.required_capabilities,
            executable_source,
            str(executable) if executable else None,
        )
        if expected_state is not None and not self._service_identity_matches(
            expected_state.summary, summary
        ):
            raise _ImagePreparationFailure(
                "SERVICE_RESOURCE_CHANGED",
                "Flash Service resources changed after validation",
                image_path=str(image_path),
                map_path=str(map_path),
            )
        return prepared, summary

    @staticmethod
    def _service_identity_matches(
        expected: PreparedFlashServiceSummary | None,
        actual: PreparedFlashServiceSummary,
    ) -> bool:
        if expected is None:
            return False
        ignored = {"tool_configuration_revision"} if actual.image_source_kind is ImageSourceKind.TXT else set()
        return all(
            getattr(expected, name) == getattr(actual, name)
            for name in expected.__dataclass_fields__
            if name not in ignored
        )

    def _materialize_ram_app(
        self,
        *,
        target_key: str,
        source_path: str,
        expected_identity: RamImageIdentity | None,
        target_profile: TargetProfile,
    ) -> tuple[
        PreparedRamImage,
        SourceFileFingerprint,
        ImageSourceKind,
        Hex2000Source,
        str | None,
    ]:
        target = self._validate_target_profile(target_key, target_profile)
        if expected_identity is not None and type(expected_identity) is not RamImageIdentity:
            raise TypeError("expected_identity must be the canonical RamImageIdentity or None")
        path, source_kind, before, executable, executable_source = (
            self._resolve_local_image(source_path)
        )
        try:
            if source_kind is ImageSourceKind.OUT:
                with ImageMaterializationWorkspace(
                    path, self._sci8_temp_dir or None
                ) as materialization:
                    prepared = self._prepare_ram_operation(
                        path,
                        target=target,
                        hex2000=str(executable),
                        sci8_txt=materialization.sci8_path,
                    )
                    generated = getattr(prepared, "generated_sci8_txt", None)
                    if (
                        type(prepared) is PreparedRamImage
                        and isinstance(generated, (str, Path))
                        and Path(generated).expanduser().resolve(strict=False)
                        == materialization.sci8_path.expanduser().resolve(strict=False)
                    ):
                        prepared = replace(prepared, generated_sci8_txt=None)
            else:
                prepared = self._prepare_ram_operation(path, target=target)
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
        if type(prepared) is not PreparedRamImage:
            raise _ImagePreparationFailure(
                "IMAGE_VALIDATION_FAILED",
                "RAM App preparation returned an invalid result",
            )
        after = self._fingerprint(path, during_preparation=True)
        if before != after:
            raise _ImagePreparationFailure(
                "IMAGE_CHANGED_DURING_PREPARATION",
                "The source image changed during preparation",
            )
        identity = RamImageIdentity(
            prepared.entry_point, prepared.total_words, prepared.image_crc32
        )
        if expected_identity is not None and identity != expected_identity:
            raise _ImagePreparationFailure(
                "IMAGE_CHANGED",
                "The RAM App no longer matches the selected RAM image",
            )
        return prepared, after, source_kind, executable_source, (
            str(executable) if executable else None
        )

    def _resolve_target_profile(self, target_key: str) -> TargetProfile:
        try:
            target_profile = self._target_profile_resolver(target_key)
        except Exception as exc:
            raise _ImagePreparationFailure(
                "TARGET_PROFILE_RESOLUTION_FAILED",
                f"Target Profile resolution failed: {exc}",
            ) from exc
        if target_profile is None:
            raise _ImagePreparationFailure(
                "TARGET_PROFILE_UNAVAILABLE",
                f"No Target Profile is registered for {target_key}",
            )
        return self._validate_target_profile(target_key, target_profile)

    @staticmethod
    def _validate_target_profile(
        target_key: str, target_profile: TargetProfile
    ) -> TargetProfile:
        if not isinstance(target_profile, TargetProfile):
            raise _ImagePreparationFailure(
                "TARGET_PROFILE_INVALID", "Target Profile is invalid"
            )
        try:
            profile_key = f"cpu{int(target_profile.cpu_id)}"
        except (TypeError, ValueError, OverflowError) as exc:
            raise _ImagePreparationFailure(
                "TARGET_PROFILE_INVALID", "Target Profile CPU ID is invalid"
            ) from exc
        if profile_key != target_key:
            raise _ImagePreparationFailure(
                "TARGET_PROFILE_MISMATCH",
                f"Target Profile CPU {profile_key} does not match {target_key}",
            )
        return target_profile

    def _materialize_flash_app(
        self,
        *,
        target_key: str,
        target_profile: TargetProfile,
        source_path: str,
        expected_identity: ImageIdentity | None,
        expected_effective_sector_mask: int | None,
    ) -> tuple[
        PreparedFlashImage,
        SourceFileFingerprint,
        ImageSourceKind,
        Hex2000Source,
        str | None,
    ]:
        target = self._validate_target_profile(target_key, target_profile)
        if expected_identity is not None and type(expected_identity) is not ImageIdentity:
            raise TypeError("expected_identity must be the canonical ImageIdentity or None")
        if expected_effective_sector_mask is not None and (
            type(expected_effective_sector_mask) is not int
            or expected_effective_sector_mask <= 0
        ):
            raise ValueError("expected_effective_sector_mask must be positive or None")
        try:
            path, source_kind, before, executable, executable_source = (
                self._resolve_local_image(source_path)
            )
        except _ImagePreparationFailure as exc:
            if exc.code == "IMAGE_FILE_NOT_FOUND":
                raise _ImagePreparationFailure("IMAGE_FILE_ACCESS_FAILED", str(exc)) from exc
            raise
        try:
            if source_kind is ImageSourceKind.OUT:
                with ImageMaterializationWorkspace(
                    path, self._sci8_temp_dir or None
                ) as materialization:
                    prepared = self._prepare_flash_operation(
                        path,
                        target=target,
                        hex2000=str(executable),
                        sci8_txt=materialization.sci8_path,
                    )
                    generated = getattr(prepared, "generated_sci8_txt", None)
                    if (
                        type(prepared) is PreparedFlashImage
                        and isinstance(generated, (str, Path))
                        and Path(generated).expanduser().resolve(strict=False)
                        == materialization.sci8_path.expanduser().resolve(strict=False)
                    ):
                        prepared = replace(prepared, generated_sci8_txt=None)
            else:
                prepared = self._prepare_flash_operation(path, target=target)
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
        if type(prepared) is not PreparedFlashImage:
            raise _ImagePreparationFailure(
                "IMAGE_VALIDATION_FAILED",
                "Flash App preparation returned an invalid result",
            )
        after = self._fingerprint(path, during_preparation=True)
        if before != after:
            raise _ImagePreparationFailure(
                "IMAGE_CHANGED_DURING_PREPARATION",
                "The source image changed during preparation",
            )
        if (
            expected_identity is not None
            and prepared.identity != expected_identity
        ) or (
            expected_effective_sector_mask is not None
            and prepared.sector_mask != expected_effective_sector_mask
        ):
            raise _ImagePreparationFailure(
                "IMAGE_CHANGED",
                "The Flash App no longer matches the selected Program image",
            )
        return (
            prepared,
            after,
            source_kind,
            executable_source,
            str(executable) if executable else None,
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
        if captured is None:
            return self._ram_request_failure(task_id, "STALE_CONNECTION", "The connected target changed", request)
        if captured[3] != request.target_key:
            return self._ram_request_failure(task_id, "STALE_TARGET", "The connected target changed", request)
        cpu_id = RuntimeCpuId.from_target_key(captured[3])
        connection_generation = captured[4]
        resource, problem = self._ram_operation_state(request)
        if problem is not None:
            if isinstance(request, RunAdvancedRamImageRequest):
                return self._ram_request_failure(
                    task_id,
                    "RAM_CRC_EVIDENCE_REQUIRED",
                    "Run Check CRC for the current RAM image and connection first",
                    request,
                )
            return self._ram_request_failure(task_id, *problem, request)

        fields = (
            ("ram_load_begin", "ram_load_data", "ram_load_end")
            if isinstance(request, LoadAdvancedRamImageRequest)
            else (("ram_check_crc",) if isinstance(request, CheckAdvancedRamCrcRequest) else ("run_ram",))
        )
        if any(getattr(captured[1].command_set, field) is None for field in fields):
            return self._ram_request_failure(task_id, "UNSUPPORTED_OPERATION", "The current target does not support this RAM operation", request)
        if isinstance(request, RunAdvancedRamImageRequest) and not self._ram_crc_evidence_matches(
            request, captured, cpu_id, resource, connection_generation
        ):
            return self._ram_request_failure(
                task_id,
                "RAM_CRC_EVIDENCE_REQUIRED",
                "Run Check CRC for the current RAM image and connection first",
                request,
            )

        image = None
        image_fingerprint = None
        identity = request.expected_image_identity
        if not isinstance(request, RunAdvancedRamImageRequest):
            runtime_operation_type = (
                RuntimeOperationType.RAM_LOAD
                if isinstance(request, LoadAdvancedRamImageRequest)
                else RuntimeOperationType.RAM_CRC
            )
            self._runtime_v2_dispatcher.dispatch(
                OperationStarted(
                    task_id,
                    runtime_operation_type,
                    cpu_id,
                    connection_generation,
                    request.expected_image_identity,
                )
            )
            try:
                image, image_fingerprint, _kind, _source, _executable = (
                    self._materialize_ram_app(
                        target_key=request.target_key,
                        source_path=request.image_source_path,
                        expected_identity=request.expected_image_identity,
                        target_profile=captured[1],
                    )
                )
            except _ImagePreparationFailure as exc:
                _resource, problem = self._ram_operation_state(request)
                if problem is not None:
                    return self._ram_request_failure(task_id, *problem, request)
                self._fail_ram_image_parse(cpu_id, request.image_source_path, request.selection_revision, exc.code, str(exc))
                return self._ram_request_failure(task_id, exc.code, str(exc), request)
            if (
                self._status_connection(request.connection_id, captured) is None
                or self.connection_generation != connection_generation
            ):
                return self._ram_request_failure(task_id, "STALE_CONNECTION", "The connection changed during RAM image preparation", request)
            _resource, problem = self._ram_operation_state(request)
            if problem is not None:
                return self._ram_request_failure(task_id, *problem, request)
            identity = RamImageIdentity(
                image.entry_point, image.total_words, image.image_crc32
            )

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
            result = self._run_ram_operation(
                context, RunRamImageRequest(request.expected_ram_crc_evidence.entry_point)
            )
        if not isinstance(result, OperationResult):
            raise TypeError("RAM operation returned an invalid result")
        if self._status_connection(request.connection_id, captured) is None:
            return self._ram_request_failure(task_id, "STALE_CONNECTION", "The connection changed during the RAM operation", request)
        if isinstance(request, CheckAdvancedRamCrcRequest):
            self._dispatch_clean_ram_crc_success(
                task_id,
                request,
                captured,
                connection_generation,
                image,
                image_fingerprint,
                result,
            )
        if result.ok:
            if last_update is None:
                self._publish(task_id, step_id, TaskStepState.COMPLETED, result.stage, result.operation, progress)
            elif progress is not None:
                progress(replace(last_update, step_state=TaskStepState.COMPLETED))
        operation_type = (
            AdvancedRamOperationType.LOAD
            if isinstance(request, LoadAdvancedRamImageRequest)
            else AdvancedRamOperationType.CHECK_CRC
            if isinstance(request, CheckAdvancedRamCrcRequest)
            else AdvancedRamOperationType.RUN
        )
        payload = AdvancedRamOperationSnapshot(
            request.connection_id,
            request.target_key,
            request.selection_revision,
            identity,
            operation_type,
            request.expected_ram_crc_evidence
            if isinstance(request, RunAdvancedRamImageRequest)
            else None,
            result,
        )
        action = TaskCompletionAction.RELEASE_CONNECTION if isinstance(request, RunAdvancedRamImageRequest) else TaskCompletionAction.NONE
        return operation_result_to_task_result(
            task_id,
            result,
            success_summary=request.title,
            success_message=result.stage,
            payload=payload,
            completion_action=action,
        )

    def _ram_crc_evidence_matches(
        self, request, captured, cpu_id, resource, connection_generation
    ) -> bool:
        evidence = request.expected_ram_crc_evidence
        snapshot = self.runtime_v2_snapshot
        connection = snapshot.connection
        summary = resource.ram_image_summary
        return bool(
            type(evidence) is RamCrcEvidence
            and evidence == resource.ram_crc_evidence
            and evidence.cpu_id is cpu_id
            and evidence.connection_generation == connection_generation
            and snapshot.connection_generation == connection_generation
            and connection is not None
            and connection.connection_id == request.connection_id
            and connection.cpu_id is cpu_id
            and connection.generation == evidence.connection_generation
            and captured[3] == request.target_key
            and evidence.ram_image_identity == request.expected_image_identity
            and resource.ram_image_parse_status is ImageParseStatus.READY
            and summary is not None
            and summary.identity == evidence.ram_image_identity
            and self.ram_image_revision(request.target_key) == request.selection_revision
            and evidence.entry_point == evidence.ram_image_identity.entry_point
            and evidence.image_crc32 == evidence.ram_image_identity.image_crc32
        )

    def _dispatch_clean_ram_crc_success(
        self,
        task_id,
        request,
        captured,
        connection_generation,
        image,
        source_fingerprint,
        result,
    ) -> None:
        total_words = result.summary.get("total_words")
        image_crc32 = result.summary.get("image_crc32")
        if not (
            type(image) is PreparedRamImage
            and type(source_fingerprint) is SourceFileFingerprint
            and result.completion is OperationCompletion.SUCCEEDED
            and result.ok
            and result.target == captured[1].name
            and type(total_words) is int
            and total_words == image.total_words
            and type(image_crc32) is int
            and image_crc32 == image.image_crc32
        ):
            return
        try:
            fingerprint = self._fingerprint(Path(request.image_source_path))
        except _ImagePreparationFailure:
            return
        if fingerprint != source_fingerprint:
            return
        resource, problem = self._ram_operation_state(request)
        identity = RamImageIdentity(image.entry_point, image.total_words, image.image_crc32)
        cpu_id = RuntimeCpuId.from_target_key(request.target_key)
        runtime = self.runtime_v2_snapshot
        connection = runtime.connection
        if not (
            problem is None
            and resource.ram_image_summary is not None
            and self._status_connection(request.connection_id, captured) is not None
            and self.connection_generation == connection_generation
            and runtime.connection_generation == connection_generation
            and connection is not None
            and connection.connection_id == request.connection_id
            and connection.cpu_id is cpu_id
            and connection.generation == connection_generation
            and identity == request.expected_image_identity
            and resource.ram_image_summary.identity == identity
        ):
            return
        self._runtime_v2_dispatcher.dispatch(
            OperationSucceeded(
                task_id,
                RuntimeOperationType.RAM_CRC,
                cpu_id,
                connection_generation,
                identity,
            )
        )

    def _ram_operation_state(self, request):
        cpu_id = RuntimeCpuId.from_target_key(request.target_key)
        resource = self.target_resources[cpu_id]
        with self._image_lock:
            revision = self._ram_image_revisions[cpu_id]
            tool_revision = self._configuration_revision
        if (
            resource.ram_image_parse_status is not ImageParseStatus.READY
            or resource.ram_image_summary is None
        ):
            return resource, (
                "PREPARED_RAM_IMAGE_REQUIRED",
                "Prepare the current target RAM image first",
            )
        if (
            revision != request.selection_revision
            or resource.ram_image_summary.identity != request.expected_image_identity
        ):
            return resource, (
                "STALE_IMAGE_CONFIGURATION",
                "The RAM image selection changed",
            )
        if isinstance(request, RunAdvancedRamImageRequest):
            return resource, None
        try:
            current_path = self._normalized_ram_path(resource.ram_image_path)
        except (OSError, RuntimeError, ValueError):
            current_path = ""
        if current_path != request.image_source_path:
            return resource, (
                "STALE_IMAGE_CONFIGURATION",
                "The RAM image selection changed",
            )
        if (
            Path(request.image_source_path).suffix.lower() == ".out"
            and tool_revision != request.image_tool_configuration_revision
        ):
            return resource, (
                "STALE_IMAGE_CONFIGURATION",
                "The RAM image tool configuration changed",
            )
        return resource, None

    def _program_operation_state(self, request):
        cpu_id = RuntimeCpuId.from_target_key(request.target_key)
        resource = self.target_resources[cpu_id]
        try:
            current_path = self._normalized_program_path(resource.program_image_path)
        except (OSError, RuntimeError, ValueError):
            current_path = ""
        with self._image_lock:
            revision = self._program_image_revisions[cpu_id]
            tool_revision = self._configuration_revision
            service_state = self._flash_service_resource_state
        if (
            resource.program_image_parse_status is not ImageParseStatus.READY
            or resource.program_image_summary is None
        ):
            return None, service_state, (
                "PREPARED_FLASH_IMAGE_REQUIRED",
                f"Prepare the {request.target_key.upper()} Program image first",
            )
        if (
            current_path != request.image_source_path
            or revision != request.image_selection_revision
            or resource.program_image_summary.identity != request.expected_image_identity
            or resource.program_image_summary.sector_mask
            != request.expected_effective_sector_mask
        ):
            return None, service_state, (
                "STALE_IMAGE_CONFIGURATION",
                "The Program image selection changed",
            )
        if (
            Path(request.image_source_path).suffix.lower() == ".out"
            and tool_revision != request.image_tool_configuration_revision
        ):
            return None, service_state, (
                "STALE_IMAGE_CONFIGURATION",
                "The Program image tool configuration changed",
            )
        return resource, service_state, None

    def _execute_advanced_flash_operation(
        self, task_id, request, cancellation, progress
    ) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None:
            return self._advanced_flash_request_failure(
                task_id, "STALE_CONNECTION", "The active connection changed", request
            )
        cpu_id = RuntimeCpuId.from_target_key(request.target_key)
        runtime = self.runtime_v2_snapshot
        connection = runtime.connection
        if not (
            connection is not None
            and request.expected_connection_generation == runtime.connection_generation
            and request.expected_connection_generation == self.connection_generation
            and connection.connection_id == request.connection_id
            and connection.cpu_id is cpu_id
            and connection.generation == request.expected_connection_generation
            and captured[4] == request.expected_connection_generation
        ):
            return self._advanced_flash_request_failure(
                task_id, "STALE_CONNECTION", "The connection generation changed", request
            )
        if (
            captured[3] != request.target_key
            or RuntimeCpuId.from_target_key(captured[3]) is not cpu_id
            or int(captured[1].cpu_id) != int(cpu_id.value[-1])
        ):
            return self._advanced_flash_request_failure(
                task_id, "STALE_TARGET", "The connected target changed", request
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
            (*common, "erase", "get_metadata_summary")
            if isinstance(request, EraseAdvancedFlashRequest)
            else (*common, "program_begin", "program_data", "program_end", "get_metadata_summary")
            if isinstance(request, ProgramAdvancedFlashRequest)
            else (*common, "verify_begin", "verify_data", "verify_end")
        )
        if any(getattr(captured[1].command_set, field) is None for field in required):
            return self._advanced_flash_request_failure(
                task_id, "UNSUPPORTED_OPERATION", "The current target lacks required Flash capabilities", request
            )

        resource, service_state, problem = self._program_operation_state(request)
        if problem is not None:
            return self._advanced_flash_request_failure(task_id, *problem, request)
        if (
            service_state.status is not FlashServiceResourceStatus.READY
            or service_state.summary is None
        ):
            return self._advanced_flash_request_failure(
                task_id, "PREPARED_FLASH_SERVICE_REQUIRED", f"Prepare the {request.target_key.upper()} Flash Service first", request
            )
        if (
            service_state.revision != request.service_configuration_revision
            or self._configuration_revision != request.service_tool_configuration_revision
            or service_state.summary != request.expected_service_summary
            or service_state.summary.target_key != request.target_key
        ):
            return self._advanced_flash_request_failure(
                task_id, "STALE_SERVICE_CONFIGURATION", "The Flash Service configuration changed", request
            )

        erase_scope = None
        erase_mask = None
        image = None
        image_fingerprint = None
        if isinstance(request, EraseAdvancedFlashRequest):
            erase_scope = request.erase_scope
            if erase_scope is AdvancedFlashEraseScope.REQUIRED_APP_SECTORS:
                erase_mask = request.expected_effective_sector_mask
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

        runtime_operation_type = (
            RuntimeOperationType.ERASE
            if isinstance(request, EraseAdvancedFlashRequest)
            else RuntimeOperationType.PROGRAM
            if isinstance(request, ProgramAdvancedFlashRequest)
            else RuntimeOperationType.VERIFY
        )
        event_identity = (
            request.expected_image_identity
            if not isinstance(request, EraseAdvancedFlashRequest)
            or request.erase_scope is AdvancedFlashEraseScope.REQUIRED_APP_SECTORS
            else None
        )
        connection_generation = self.connection_generation
        self._runtime_v2_dispatcher.dispatch(
            OperationStarted(
                task_id,
                runtime_operation_type,
                cpu_id,
                connection_generation,
                event_identity,
            )
        )

        needs_image = not isinstance(request, EraseAdvancedFlashRequest) or (
            request.erase_scope is AdvancedFlashEraseScope.REQUIRED_APP_SECTORS
        )
        if needs_image:
            try:
                image, image_fingerprint, _kind, _source, _executable = (
                    self._materialize_flash_app(
                        target_key=request.target_key,
                        target_profile=captured[1],
                        source_path=request.image_source_path,
                        expected_identity=request.expected_image_identity,
                        expected_effective_sector_mask=request.expected_effective_sector_mask,
                    )
                )
            except _ImagePreparationFailure as exc:
                self._fail_program_image_parse(
                    cpu_id,
                    request.image_source_path,
                    request.image_selection_revision,
                    exc.code,
                    str(exc),
                )
                return self._advanced_flash_request_failure(task_id, exc.code, str(exc), request)
            _resource, current_service_state, problem = self._program_operation_state(request)
            if problem is not None:
                return self._advanced_flash_request_failure(task_id, *problem, request)
            if current_service_state != service_state:
                return self._advanced_flash_request_failure(
                    task_id, "STALE_SERVICE_CONFIGURATION", "The Flash Service configuration changed", request
                )
            if self._status_connection(request.connection_id, captured) is None:
                return self._advanced_flash_request_failure(
                    task_id, "STALE_CONNECTION", "The connection changed during image preparation", request
                )

        try:
            service_image, _service_summary = self._materialize_flash_service(
                target_key=request.target_key,
                target_profile=captured[1],
                expected_state=service_state
            )
        except _ImagePreparationFailure as exc:
            self._set_service_failure_state(exc, request.service_configuration_revision)
            return self._advanced_flash_request_failure(
                task_id, exc.code, str(exc), request
            )

        step_id = request.step_id
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
        if isinstance(request, VerifyAdvancedFlashRequest):
            self._dispatch_clean_verify_success(
                task_id,
                request,
                captured,
                connection_generation,
                image,
                image_fingerprint,
                result,
            )
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
        primary_task_result = operation_result_to_task_result(
            task_id,
            result,
            success_summary=request.title,
            success_message=result.stage,
            payload=payload,
            completion_action=TaskCompletionAction.NONE,
        )
        if operation_type is AdvancedFlashOperationType.VERIFY_ONLY or result.completion not in {
            OperationCompletion.SUCCEEDED,
            OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
        }:
            return primary_task_result

        refresh, metadata_snapshot, refresh_error = self._refresh_metadata_after_write(
            task_id, request.connection_id, captured, progress
        )
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
            refresh,
            operation_result_to_dict(refresh) if refresh is not None else None,
            metadata_snapshot,
        )
        if refresh_error is not None:
            return self._metadata_refresh_warning_result(
                task_id, request.title, result, refresh, refresh_error,
                connection_generation, payload,
            )
        return replace(
            primary_task_result,
            step_results=(result, refresh),
            payload=payload,
        )

    def _dispatch_clean_verify_success(
        self,
        task_id,
        request,
        captured,
        connection_generation,
        image,
        source_fingerprint,
        result,
    ) -> None:
        cpu_id = RuntimeCpuId.from_target_key(request.target_key)
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
        if type(image) is not PreparedFlashImage or type(source_fingerprint) is not SourceFileFingerprint:
            return
        try:
            fingerprint = self._fingerprint(Path(request.image_source_path))
        except _ImagePreparationFailure:
            return
        if fingerprint != source_fingerprint:
            return
        resource, _service_state, problem = self._program_operation_state(request)
        if problem is not None or resource is None:
            return
        if not (
            self._status_connection(request.connection_id, captured) is not None
            and captured[3] == request.target_key
            and RuntimeCpuId.from_target_key(captured[3]) is cpu_id
            and captured[1].cpu_id == int(cpu_id.value[-1])
            and self.connection_generation == connection_generation
            and self._configuration_revision == request.image_tool_configuration_revision
            and image.identity == request.expected_image_identity
            and image.sector_mask == request.expected_effective_sector_mask
        ):
            return
        self._runtime_v2_dispatcher.dispatch(
            OperationSucceeded(
                task_id,
                RuntimeOperationType.VERIFY,
                cpu_id,
                connection_generation,
                image.identity,
            )
        )

    def _execute_advanced_metadata_operation(
        self, task_id, request, cancellation, progress
    ) -> TaskExecutionResult:
        captured = self._status_connection(request.connection_id)
        if captured is None:
            return self._metadata_request_failure(
                task_id, "STALE_CONNECTION", "The active connection changed", request
            )
        try:
            cpu_id = RuntimeCpuId.from_target_key(request.target_key)
        except (TypeError, ValueError):
            return self._metadata_request_failure(
                task_id, "STALE_TARGET", "The requested target is invalid", request
            )
        runtime = self.runtime_v2_snapshot
        connection = runtime.connection
        if not (
            connection is not None
            and request.expected_connection_generation == runtime.connection_generation
            and request.expected_connection_generation == self.connection_generation
            and connection.connection_id == request.connection_id
            and connection.cpu_id is cpu_id
            and connection.generation == request.expected_connection_generation
            and captured[4] == request.expected_connection_generation
        ):
            return self._metadata_request_failure(
                task_id, "STALE_CONNECTION", "The connection generation changed", request
            )
        if (
            captured[3] != request.target_key
            or RuntimeCpuId.from_target_key(captured[3]) is not cpu_id
            or int(captured[1].cpu_id) != int(cpu_id.value[-1])
        ):
            return self._metadata_request_failure(
                task_id, "STALE_TARGET", "The connected target changed", request
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

        image_valid_request = isinstance(request, WriteAdvancedImageValidRequest)
        if image_valid_request:
            _resource, service_state, problem = self._program_operation_state(request)
            if problem is not None:
                return self._metadata_request_failure(task_id, *problem, request)
        else:
            service_state = self.flash_service_resource_state
        if (
            service_state.status is not FlashServiceResourceStatus.READY
            or service_state.summary is None
        ):
            return self._metadata_request_failure(
                task_id, "PREPARED_FLASH_SERVICE_REQUIRED", f"Prepare the {request.target_key.upper()} Flash Service first", request
            )
        if (
            service_state.revision != request.service_configuration_revision
            or self._configuration_revision != request.service_tool_configuration_revision
            or service_state.summary != request.expected_service_summary
            or service_state.summary.target_key != request.target_key
        ):
            return self._metadata_request_failure(
                task_id, "STALE_SERVICE_CONFIGURATION", "The Flash Service configuration changed", request
            )

        if isinstance(
            request, (WriteAdvancedBootAttemptRequest, WriteAdvancedAppConfirmedRequest)
        ):
            metadata_state = runtime.metadata_state
            metadata_snapshot = metadata_state.value
            if not (
                metadata_state.freshness is DataFreshness.FRESH
                and metadata_snapshot == request.expected_metadata_snapshot
                and metadata_snapshot.connection_id == request.connection_id
                and metadata_snapshot.target_key == request.target_key
            ):
                return self._metadata_request_failure(
                    task_id,
                    "STALE_METADATA_CONFIGURATION",
                    "The Metadata snapshot changed",
                    request,
                )

        if isinstance(request, WriteAdvancedImageValidRequest) and not self._verify_evidence_matches(request):
            return self._metadata_request_failure(
                task_id,
                "VERIFY_EVIDENCE_REQUIRED",
                "Run a clean Verify Only for the current image and connection first",
                request,
            )

        image = None
        if image_valid_request:
            try:
                image, _app_fingerprint, _kind, _source, _executable = (
                    self._materialize_flash_app(
                        target_key=request.target_key,
                        target_profile=captured[1],
                        source_path=request.image_source_path,
                        expected_identity=request.expected_image_identity,
                        expected_effective_sector_mask=request.expected_effective_sector_mask,
                    )
                )
            except _ImagePreparationFailure as exc:
                self._fail_program_image_parse(
                    cpu_id,
                    request.image_source_path,
                    request.image_selection_revision,
                    exc.code,
                    str(exc),
                )
                return self._metadata_request_failure(task_id, exc.code, str(exc), request)
            _resource, current_service_state, problem = self._program_operation_state(request)
            if problem is not None:
                return self._metadata_request_failure(task_id, *problem, request)
            if current_service_state != service_state:
                return self._metadata_request_failure(
                    task_id, "STALE_SERVICE_CONFIGURATION", "Prepared Flash Service changed before Metadata execution", request
                )
        if self._status_connection(request.connection_id, captured) is None:
            return self._metadata_request_failure(
                task_id, "STALE_CONNECTION", "The active connection changed before Metadata execution", request
            )

        operation_type: AdvancedMetadataOperationType
        verify_evidence = None
        if isinstance(request, WriteAdvancedImageValidRequest):
            operation_type = AdvancedMetadataOperationType.WRITE_IMAGE_VALID
            verify_evidence = request.expected_verify_evidence
            if not self._verify_evidence_matches(request, image.identity):
                return self._metadata_request_failure(
                    task_id,
                    "VERIFY_EVIDENCE_REQUIRED",
                    "Run a clean Verify Only for the current image and connection first",
                    request,
                )
            operation = self._append_image_valid_operation
            operation_request = AppendImageValidRequest(image)
        elif isinstance(request, WriteAdvancedBootAttemptRequest):
            operation_type = AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT
            operation = self._append_boot_attempt_operation
            operation_request = AppendBootAttemptRequest()
        else:
            operation_type = AdvancedMetadataOperationType.WRITE_APP_CONFIRMED
            operation = self._append_app_confirmed_operation
            operation_request = AppendAppConfirmedRequest()

        try:
            service, _service_summary = self._materialize_flash_service(
                target_key=request.target_key,
                target_profile=captured[1],
                expected_state=service_state
            )
        except _ImagePreparationFailure as exc:
            self._set_service_failure_state(exc, request.service_configuration_revision)
            return self._metadata_request_failure(task_id, exc.code, str(exc), request)
        if image_valid_request and not self._verify_evidence_matches(request, image.identity):
            return self._metadata_request_failure(
                task_id,
                "VERIFY_EVIDENCE_REQUIRED",
                "Run a clean Verify Only for the current image and connection first",
                request,
            )

        step_id = request.step_id
        connection_generation = self.connection_generation
        self._runtime_v2_dispatcher.dispatch(
            MetadataWriteStarted(
                task_id,
                cpu_id,
                connection_generation,
                image.identity if image is not None else None,
            )
        )
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
            request, operation_type, verify_evidence, image.identity if image is not None else None, primary
        )
        if primary.completion not in {
            OperationCompletion.SUCCEEDED,
            OperationCompletion.COMPLETED_AFTER_CANCEL_REQUEST,
        }:
            return operation_result_to_task_result(task_id, primary, payload=payload)
        readback, metadata_snapshot, refresh_error = self._refresh_metadata_after_write(
            task_id, request.connection_id, captured, progress
        )
        payload = self._metadata_payload(
            request, operation_type, verify_evidence,
            image.identity if image is not None else None,
            primary, readback, metadata_snapshot,
        )
        if refresh_error is not None:
            return self._metadata_refresh_warning_result(
                task_id, request.title, primary, readback, refresh_error,
                connection_generation, payload,
            )
        raw = metadata_snapshot.raw_metadata
        if not self._metadata_readback_matches(
            operation_type, primary, raw,
            image.identity if image is not None else None,
            metadata_snapshot, request.expected_metadata_snapshot,
        ):
            payload = self._metadata_payload(
                request, operation_type, verify_evidence, image.identity if image is not None else None,
                primary, readback, metadata_snapshot,
            )
            return self._metadata_failure(
                task_id, "METADATA_READBACK_MISMATCH",
                "Metadata readback does not confirm the operation result",
                "GET_METADATA_SUMMARY", payload, (primary, readback), ask_disconnect=True,
            )
        payload = self._metadata_payload(
            request, operation_type, verify_evidence, image.identity if image is not None else None,
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

    def _refresh_metadata_after_write(
        self, task_id, connection_id, captured, progress
    ) -> tuple[OperationResult | None, MetadataStatusSnapshot | None, RuntimeReadError | None]:
        stage = "GET_METADATA_SUMMARY"
        if self._status_connection(connection_id, captured) is None:
            return None, None, RuntimeReadError(
                "STALE_CONNECTION", "The connection changed before Metadata refresh", stage
            )
        self._publish(
            task_id,
            "read_metadata_summary",
            TaskStepState.STARTED,
            stage,
            "Reading Metadata Summary",
            progress,
        )
        refresh = None
        try:
            refresh = self._metadata_operation(OperationContext(captured[0], captured[1]))
            if not isinstance(refresh, OperationResult):
                raise TypeError("Metadata refresh returned an invalid result")
            if self._status_connection(connection_id, captured) is None:
                return refresh, None, RuntimeReadError(
                    "STALE_CONNECTION", "The connection changed during Metadata refresh", stage
                )
            if not refresh.ok:
                error = self._read_error(refresh)
                self._dispatch_metadata_failure(captured, error)
                return refresh, None, error
            raw = MetadataSummary(**dict(refresh.summary))
            snapshot = self._metadata_snapshot(
                MetadataRefreshRequest(connection_id, True), captured[3], refresh, raw
            )
            if self._status_connection(connection_id, captured) is None:
                return refresh, None, RuntimeReadError(
                    "STALE_CONNECTION", "The connection changed after Metadata refresh", stage
                )
            self._runtime_v2_dispatcher.dispatch(
                MetadataReadSucceeded(
                    RuntimeCpuId.from_target_key(captured[3]), captured[4], snapshot
                )
            )
            self._publish(
                task_id,
                "read_metadata_summary",
                TaskStepState.COMPLETED,
                refresh.stage,
                refresh.operation,
                progress,
            )
            return refresh, snapshot, None
        except Exception as exc:
            error = RuntimeReadError(
                type(exc).__name__, str(exc) or type(exc).__name__, stage
            )
            self._dispatch_metadata_failure(captured, error)
            return refresh, None, error

    @staticmethod
    def _metadata_refresh_warning_result(
        task_id,
        title,
        primary,
        refresh,
        refresh_error,
        connection_generation,
        payload,
    ) -> TaskExecutionResult:
        base = operation_result_to_task_result(
            task_id,
            primary,
            success_summary=title,
            success_message=primary.stage,
            payload=payload,
            completion_action=TaskCompletionAction.NONE,
        )
        details = {
            "primary_operation": primary.operation,
            "primary_stage": primary.stage,
            "primary_completion": primary.completion.name,
            "refresh_error_code": refresh_error.code,
            "refresh_error_message": refresh_error.message,
            "refresh_error_stage": refresh_error.stage,
            "refresh_error_details": (
                dict(refresh.error.details)
                if refresh is not None and refresh.error is not None
                else {}
            ),
            "connection_generation": connection_generation.value,
            "metadata_freshness": DataFreshness.STALE.value,
            "primary_retry_performed": False,
        }
        if primary.cancellation is not None:
            details["primary_cancel_requested"] = True
            details["primary_cancellation"] = (
                dict(base.warning.details) if base.warning is not None else {}
            )
        message = (
            f"{title} completed, but Metadata refresh failed: {refresh_error.message}"
        )
        return replace(
            base,
            summary=title,
            message=message,
            step_results=(primary,) + ((refresh,) if refresh is not None else ()),
            payload=payload,
            warning=GuiTaskWarning(
                "METADATA_REFRESH_FAILED", message, refresh_error.stage, details
            ),
        )

    def _verify_evidence_matches(self, request, identity=None) -> bool:
        try:
            cpu_id = RuntimeCpuId.from_target_key(request.target_key)
            evidence = request.expected_verify_evidence
            snapshot = self.runtime_v2_snapshot
            resource = snapshot.target_resources.get(cpu_id)
            connection = snapshot.connection
            return bool(
                resource is not None
                and resource.cpu_id is cpu_id
                and type(evidence) is VerifyEvidence
                and evidence == resource.verify_evidence
                and evidence.cpu_id is cpu_id
                and connection is not None
                and connection.cpu_id is cpu_id
                and connection.connection_id == request.connection_id
                and connection.generation == snapshot.connection_generation
                and connection.generation == self.connection_generation
                and connection.generation == request.expected_connection_generation
                and connection.generation == evidence.connection_generation
                and resource.program_image_summary is not None
                and resource.program_image_summary.identity == request.expected_image_identity
                and evidence.image_identity == request.expected_image_identity
                and self.program_image_revision(request.target_key) == request.image_selection_revision
                and self._configuration_revision == request.image_tool_configuration_revision
                and (identity is None or identity == evidence.image_identity)
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return False

    @staticmethod
    def _metadata_readback_matches(
        operation_type, primary, raw, identity, metadata_snapshot, expected_snapshot
    ) -> bool:
        source = identity or expected_snapshot.raw_metadata
        image_matches = bool(
            metadata_snapshot.metadata_valid
            and metadata_snapshot.image_valid
            and raw.entry_point == source.entry_point
            and raw.image_size_words == source.image_size_words
            and raw.image_crc32 == source.image_crc32
        )
        if operation_type is AdvancedMetadataOperationType.WRITE_IMAGE_VALID:
            reason = primary.summary.get("reason")
            if primary.summary.get("written"):
                return image_matches
            if reason == "IMAGE_VALID_ALREADY_EXISTS":
                return metadata_snapshot.metadata_valid and metadata_snapshot.image_valid
            if reason == "METADATA_INVALID":
                return not metadata_snapshot.metadata_valid
            return False
        reason = primary.summary.get("reason")
        if reason == "METADATA_INVALID":
            return not metadata_snapshot.metadata_valid
        if reason == "IMAGE_VALID_REQUIRED":
            return not metadata_snapshot.image_valid
        if reason == "APP_CONFIRMED_ALREADY_EXISTS":
            return image_matches and metadata_snapshot.app_confirmed
        if reason == "BOOT_ATTEMPT_LIMIT_REACHED":
            return image_matches and raw.boot_attempt_count >= min(raw.boot_attempt_limit, 3)
        if reason == "BOOT_ATTEMPT_REQUIRED":
            return image_matches and raw.boot_attempt_count == 0
        if operation_type is AdvancedMetadataOperationType.WRITE_BOOT_ATTEMPT:
            expected_count = expected_snapshot.raw_metadata.boot_attempt_count
            return image_matches and raw.boot_attempt_count == expected_count + 1
        return image_matches and bool(raw.app_confirmed)

    @staticmethod
    def _metadata_payload(
        request, operation_type, verify_evidence, identity, primary,
        readback=None, metadata_snapshot=None,
    ) -> AdvancedMetadataOperationSnapshot:
        source = identity or request.expected_metadata_snapshot.raw_metadata
        return AdvancedMetadataOperationSnapshot(
            request.connection_id,
            request.target_key,
            getattr(request, "image_selection_revision", None),
            getattr(request, "image_tool_configuration_revision", None),
            request.service_configuration_revision,
            request.service_tool_configuration_revision,
            operation_type,
            verify_evidence,
            source.entry_point,
            source.image_size_words,
            source.image_crc32,
            identity.app_end if identity is not None else None,
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
                "image_selection_revision": getattr(request, "image_selection_revision", None),
                "image_tool_configuration_revision": getattr(request, "image_tool_configuration_revision", None),
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

    def _set_service_failure_state(
        self, failure: _ImagePreparationFailure, expected_revision: int
    ) -> None:
        with self._image_lock:
            state = self._flash_service_resource_state
            if state.revision != expected_revision:
                return
            unavailable = failure.code in {
                "APP_RESOURCE_PROVIDER_REQUIRED",
                "AppResourceConfigurationError",
                "AppResourceNotFoundError",
                "IMAGE_FILE_NOT_FOUND",
                "SERVICE_FILE_ACCESS_FAILED",
            }
            status = (
                FlashServiceResourceStatus.STALE
                if failure.code in {
                    "SERVICE_RESOURCE_CHANGED",
                    "SERVICE_CHANGED_DURING_PREPARATION",
                }
                else FlashServiceResourceStatus.UNAVAILABLE
                if unavailable
                else FlashServiceResourceStatus.ERROR
            )
            self._flash_service_resource_state = FlashServiceResourceState(
                state.revision + 1,
                state.provider_name,
                failure.image_path or state.image_path,
                failure.map_path or state.map_path,
                status,
                error_code=failure.code,
                error_message=str(failure),
            )

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

    @staticmethod
    def _image_failure(task_id, request, failure: _ImagePreparationFailure) -> TaskExecutionResult:
        if isinstance(request, PrepareFlashServiceRequest):
            stage = "prepare_flash_service"
            details = {
                "resource_revision": request.resource_revision,
                "tool_configuration_revision": request.tool_configuration_revision,
            }
        else:
            stage = (
                "prepare_ram_image" if isinstance(request, PrepareRamImageRequest)
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
