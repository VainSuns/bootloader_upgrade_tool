"""Single-owner runtime backend for the Batch 12 SCI session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
from threading import Lock
from typing import Any
from uuid import uuid4

from ..operations import (
    OperationContext,
    OperationResult,
    TargetDiscoveryOutcome,
    discover_connected_target,
    get_device_info,
    get_last_error,
    get_metadata_summary,
    get_protocol_info,
    operation_result_to_dict,
)
from ..firmware.hex2000 import (
    Hex2000ConfigurationError,
    Hex2000Error,
    Hex2000NotFoundError,
    Sci8ParseError,
    locate_hex2000,
)
from ..firmware.flash_layout import image_sector_mask
from ..images import PreparedFlashImage, prepare_flash_app_image
from ..protocol.boot_protocol_client import ProtocolInfo
from ..protocol.models import DeviceInfo, ErrorDetail, MetadataSummary
from ..session import UpgradeSession, UpgradeSessionConfig
from ..targets import CPU1_PROFILE
from ..targets import TargetProfile
from ..transport.base import TransportError, TransportTimeoutError
from ..transport.serial_transport import SerialTransport, SerialTransportConfig
from .connection_models import SerialConnectRequest, SerialDisconnectRequest
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
    TaskExecutionResult,
    TaskFinalStatus,
    TaskProgressUpdate,
    TaskStepState,
)
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
    ) -> None:
        self._lock = Lock()
        self._image_lock = Lock()
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
        self._status_lock = Lock()
        self._metadata_status_snapshot: MetadataStatusSnapshot | None = None
        self._device_info_operation = device_info_operation
        self._protocol_info_operation = protocol_info_operation
        self._last_error_operation = last_error_operation
        self._metadata_operation = metadata_operation

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

    @property
    def metadata_status_snapshot(self) -> MetadataStatusSnapshot | None:
        with self._status_lock:
            return self._metadata_status_snapshot

    @property
    def hex2000_executable_path(self) -> str:
        return self._hex2000_executable_path

    @property
    def sci8_temp_dir(self) -> str:
        return self._sci8_temp_dir

    def set_image_tool_paths(self, hex2000_executable_path: str, sci8_temp_dir: str) -> None:
        self._hex2000_executable_path = hex2000_executable_path.strip()
        self._sci8_temp_dir = sci8_temp_dir.strip()
        self._global_settings_error = None

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
            return self._connect(task_id, request, progress)
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
            if isinstance(request, StatusRequest):
                raise NotImplementedError(f"unsupported status request: {type(request).__name__}")
            if not isinstance(request, PrepareFlashImageRequest):
                raise NotImplementedError("RuntimeBackend only supports PrepareFlashImageRequest")
            return self._prepare_flash_image(task_id, request, progress)
        except _ImagePreparationFailure as exc:
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
        client = captured[0].client
        had_device_info = hasattr(client, "device_info")
        previous_device_info = getattr(client, "device_info", None)
        accepted = False
        try:
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
            client.device_info = info
            self._device_info = info
            accepted = True
            return final_result
        finally:
            if not accepted:
                if had_device_info:
                    client.device_info = previous_device_info
                elif hasattr(client, "device_info"):
                    del client.device_info

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

    def _connect(self, task_id, request, progress) -> TaskExecutionResult:
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
            session.connect()
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

        try:
            self._publish(task_id, "identify_target", TaskStepState.STARTED, "IDENTIFY_TARGET", "Reading DeviceInfo", progress)
            outcome = self._discovery_operation(session)
            if not isinstance(outcome, TargetDiscoveryOutcome):
                raise RuntimeError("discovery operation returned an invalid outcome")
            evidence = (outcome.result,)
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
            return result
        except Exception:
            self._cleanup_partial(session, transport)
            self._clear_active()
            raise

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
        details = {
            "selection_revision": request.selection_revision,
            "source_path": request.source_path,
        }
        if failure.__cause__ is not None:
            details["exception_type"] = type(failure.__cause__).__name__
        error = GuiRuntimeError(
            failure.code,
            str(failure),
            "prepare_flash_image",
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
