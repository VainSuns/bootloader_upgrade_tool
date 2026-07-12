"""Single-owner runtime backend for the Batch 12 SCI session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from ..operations import (
    TargetDiscoveryOutcome,
    discover_connected_target,
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
from ..protocol.models import DeviceInfo
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

TransportFactory = Callable[[SerialTransportConfig], Any]
SessionFactory = Callable[[UpgradeSessionConfig], Any]
DiscoveryOperation = Callable[[UpgradeSession], TargetDiscoveryOutcome]


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
        global_settings_error: str | None = None,
    ) -> None:
        self._lock = Lock()
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
        self._prepared_flash_image: PreparedFlashImage | None = None
        self._prepared_image_summary: PreparedImageSummary | None = None
        self._image_selection_revision: int | None = None

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
        return self._prepared_flash_image

    @property
    def prepared_image_summary(self) -> PreparedImageSummary | None:
        return self._prepared_image_summary

    @property
    def hex2000_executable_path(self) -> str:
        return self._hex2000_executable_path

    def invalidate_prepared_image_cache(self, selection_revision: int | None = None) -> None:
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
            if isinstance(request, PrepareFlashImageRequest):
                return self._prepare_flash_image(task_id, request, progress)
            raise _ImagePreparationFailure(
                "IMAGE_VALIDATION_FAILED", "Invalid image preparation request"
            )
        except _ImagePreparationFailure as exc:
            self.invalidate_prepared_image_cache()
            return self._image_failure(task_id, request, exc.code, str(exc))
        finally:
            self._lock.release()

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
            if discovered.target_key == "cpu2":
                self.invalidate_prepared_image_cache()
            self._session = session
            self._transport = transport
            self._target = discovered.target_profile
            self._device_info = discovered.device_info
            self._connection_info = self._make_connection_info(request, discovered)
            self._publish(
                task_id,
                "identify_target",
                TaskStepState.COMPLETED,
                "IDENTIFY_TARGET",
                f"Identified {discovered.target_key.upper()}",
                progress,
            )
            return TaskExecutionResult(
                task_id,
                TaskFinalStatus.SUCCEEDED,
                "Connected",
                f"Connected to {discovered.target_key.upper()}",
                step_results=evidence,
                payload=self._connection_info,
            )
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
        self._session = None
        self._transport = None
        self._target = None
        self._device_info = None
        self._connection_info = None

    def _prepare_flash_image(self, task_id, request: PrepareFlashImageRequest, progress) -> TaskExecutionResult:
        self._publish(
            task_id,
            "prepare_flash_image",
            TaskStepState.STARTED,
            "PREPARE_FLASH_IMAGE",
            "Preparing CPU1 App image",
            progress,
        )
        if self._image_selection_revision is None:
            self._image_selection_revision = request.selection_revision
        if request.selection_revision != self._image_selection_revision:
            raise _ImagePreparationFailure(
                "IMAGE_SELECTION_CHANGED", "The selected image changed before preparation started"
            )

        if not isinstance(request.source_path, str) or not request.source_path.strip():
            raise _ImagePreparationFailure("INVALID_IMAGE_PATH", "Image path must not be empty")
        try:
            path = Path(request.source_path).expanduser().resolve(strict=False)
        except (OSError, ValueError) as exc:
            raise _ImagePreparationFailure("INVALID_IMAGE_PATH", str(exc)) from exc
        source_kind = self._source_kind(path)
        before = self._fingerprint(path)
        if source_kind is ImageSourceKind.OUT and self._global_settings_error:
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
            )
        except Sci8ParseError as exc:
            raise _ImagePreparationFailure("IMAGE_PARSE_FAILED", str(exc)) from exc
        except Hex2000Error as exc:
            raise _ImagePreparationFailure("IMAGE_CONVERSION_FAILED", str(exc)) from exc
        except FileNotFoundError as exc:
            raise _ImagePreparationFailure("IMAGE_FILE_NOT_FOUND", str(exc)) from exc
        except PermissionError as exc:
            raise _ImagePreparationFailure("IMAGE_FILE_ACCESS_FAILED", str(exc)) from exc
        except ValueError as exc:
            raise _ImagePreparationFailure("IMAGE_VALIDATION_FAILED", str(exc)) from exc
        after = self._fingerprint(path, during_preparation=True)
        if before != after:
            raise _ImagePreparationFailure(
                "IMAGE_CHANGED_DURING_PREPARATION",
                "The source image changed during preparation",
            )
        if request.selection_revision != self._image_selection_revision:
            raise _ImagePreparationFailure(
                "IMAGE_SELECTION_CHANGED", "The selected image changed during preparation"
            )

        summary = self._build_image_summary(
            request,
            prepared,
            source_kind,
            after,
            hex2000_source,
            hex2000_executable,
        )
        self._prepared_flash_image = prepared
        self._prepared_image_summary = summary
        self._publish(
            task_id,
            "prepare_flash_image",
            TaskStepState.COMPLETED,
            "PREPARE_FLASH_IMAGE",
            "CPU1 App image prepared",
            progress,
        )
        return TaskExecutionResult(
            task_id,
            TaskFinalStatus.SUCCEEDED,
            "Image prepared",
            "CPU1 App image prepared",
            payload=summary,
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
            if not path.is_file():
                raise FileNotFoundError(path)
            stat = path.stat()
        except FileNotFoundError as exc:
            code = "IMAGE_CHANGED_DURING_PREPARATION" if during_preparation else "IMAGE_FILE_NOT_FOUND"
            raise _ImagePreparationFailure(code, f"Image file was not found: {path}") from exc
        except PermissionError as exc:
            raise _ImagePreparationFailure("IMAGE_FILE_ACCESS_FAILED", str(exc)) from exc
        except OSError as exc:
            raise _ImagePreparationFailure("IMAGE_FILE_ACCESS_FAILED", str(exc)) from exc
        return SourceFileFingerprint(str(path), stat.st_size, stat.st_mtime_ns)

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
    def _image_failure(task_id, request, code: str, message: str) -> TaskExecutionResult:
        details = {"selection_revision": getattr(request, "selection_revision", None)}
        error = GuiRuntimeError(
            code,
            message,
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
            message,
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
