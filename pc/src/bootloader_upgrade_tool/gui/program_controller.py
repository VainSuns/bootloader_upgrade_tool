"""GUI-side CPU1 program operation sequencing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..images import compare_flash_image_with_metadata, prepare_flash_app_image, prepare_service_image
from ..operations import (
    AppendAppConfirmedRequest,
    AppendBootAttemptRequest,
    AppendImageValidRequest,
    EraseFlashImageAreaRequest,
    FlashOperationContext,
    OperationContext,
    OperationResult,
    ProgramFlashImageRequest,
    RunFlashAppRequest,
    VerifyFlashImageRequest,
    append_app_confirmed,
    append_boot_attempt,
    append_image_valid,
    erase_flash_image_area,
    get_metadata_summary,
    program_flash_image,
    run_flash_app,
    verify_flash_image,
)
from ..protocol.models import MetadataSummary
from ..targets import CPU1_PROFILE, TargetProfile
from .global_settings import DEFAULT_DESCRIPTOR_SYMBOL


ShouldCancel = Callable[[], bool]
ProgressCallback = Callable[[Any], None]


@dataclass(frozen=True)
class LoadImageRequest:
    session: Any
    app_image_path: str | Path
    service_image_path: str | Path
    service_map_path: str | Path
    target: TargetProfile = CPU1_PROFILE
    hex2000: str | None = None
    descriptor_symbol: str = DEFAULT_DESCRIPTOR_SYMBOL
    force_load: bool = False
    auto_run_after_load: bool = False
    confirm_app: bool = False
    keep_sci8_txt: bool = False


@dataclass(frozen=True)
class RunRequest:
    session: Any
    image_identity: Any
    entry_point: int
    service: Any
    target: TargetProfile = CPU1_PROFILE
    confirm_app: bool = False


@dataclass(frozen=True)
class ControllerResult:
    status: str
    message: str
    operation_results: tuple[Any, ...] = field(default_factory=tuple)
    image: Any | None = None
    service: Any | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "skipped", "cancelled"}


@dataclass(frozen=True)
class ProgramControllerDependencies:
    prepare_flash_app_image: Callable[..., Any] = prepare_flash_app_image
    prepare_service_image: Callable[..., Any] = prepare_service_image
    get_metadata_summary: Callable[[OperationContext], Any] = get_metadata_summary
    erase_flash_image_area: Callable[[FlashOperationContext, Any], Any] = erase_flash_image_area
    program_flash_image: Callable[[FlashOperationContext, Any], Any] = program_flash_image
    verify_flash_image: Callable[[FlashOperationContext, Any], Any] = verify_flash_image
    append_image_valid: Callable[[FlashOperationContext, Any], Any] = append_image_valid
    append_boot_attempt: Callable[[FlashOperationContext, Any], Any] = append_boot_attempt
    append_app_confirmed: Callable[[FlashOperationContext, Any], Any] = append_app_confirmed
    run_flash_app: Callable[[OperationContext, Any], Any] = run_flash_app


class ProgramController:
    def __init__(self, dependencies: ProgramControllerDependencies | None = None) -> None:
        self._deps = dependencies or ProgramControllerDependencies()

    def load_image_cpu1(
        self,
        request: LoadImageRequest,
        progress: ProgressCallback | None = None,
        should_cancel: ShouldCancel | None = None,
    ) -> ControllerResult:
        results: list[Any] = []
        if self._cancelled(should_cancel):
            return ControllerResult("cancelled", "cancelled before preparing image")

        app = self._deps.prepare_flash_app_image(
            request.app_image_path,
            target=request.target,
            hex2000=request.hex2000,
            keep_sci8_txt=request.keep_sci8_txt,
        )
        if self._cancelled(should_cancel):
            return ControllerResult("cancelled", "cancelled before preparing service", image=app)

        service = self._deps.prepare_service_image(
            request.service_image_path,
            request.service_map_path,
            target=request.target,
            descriptor_symbol=request.descriptor_symbol,
            hex2000=request.hex2000,
        )
        op_ctx = OperationContext(request.session, request.target, progress)
        flash_ctx = FlashOperationContext(
            session=request.session,
            target=request.target,
            progress=progress,
            service=service,
        )

        metadata = self._step(results, self._deps.get_metadata_summary, op_ctx)
        if metadata is None:
            return ControllerResult("failed", "get_metadata_summary failed", tuple(results), app, service)

        if self._same_image(app, metadata) and not request.force_load:
            return ControllerResult("skipped", "selected image already matches metadata", tuple(results), app, service)

        steps: tuple[tuple[Callable[[FlashOperationContext, Any], Any], Any, str], ...] = (
            (self._deps.erase_flash_image_area, EraseFlashImageAreaRequest(app), "erase_flash_image_area"),
            (self._deps.program_flash_image, ProgramFlashImageRequest(app), "program_flash_image"),
            (self._deps.verify_flash_image, VerifyFlashImageRequest(app), "verify_flash_image"),
            (self._deps.append_image_valid, AppendImageValidRequest(app), "append_image_valid"),
        )
        for operation, step_request, name in steps:
            if self._cancelled(should_cancel):
                return ControllerResult("cancelled", f"cancelled before {name}", tuple(results), app, service)
            if self._step(results, operation, flash_ctx, step_request) is None:
                return ControllerResult("failed", f"{name} failed", tuple(results), app, service)

        if request.auto_run_after_load:
            run_result = self._run_cpu1_no_cancel(
                RunRequest(
                    request.session,
                    app.identity,
                    app.identity.entry_point,
                    service,
                    request.target,
                    request.confirm_app,
                ),
                progress,
            )
            results.extend(run_result.operation_results)
            if run_result.status != "ok":
                return ControllerResult(run_result.status, run_result.message, tuple(results), app, service)

        return ControllerResult("ok", "load image complete", tuple(results), app, service)

    def run_cpu1(
        self,
        request: RunRequest,
        progress: ProgressCallback | None = None,
        should_cancel: ShouldCancel | None = None,
    ) -> ControllerResult:
        if self._cancelled(should_cancel):
            return ControllerResult("cancelled", "cancelled before run sequence")
        return self._run_cpu1_no_cancel(request, progress)

    def _run_cpu1_no_cancel(self, request: RunRequest, progress: ProgressCallback | None) -> ControllerResult:
        results: list[Any] = []
        op_ctx = OperationContext(request.session, request.target, progress)
        flash_ctx = FlashOperationContext(
            session=request.session,
            target=request.target,
            progress=progress,
            service=request.service,
        )

        if self._step(results, self._deps.get_metadata_summary, op_ctx) is None:
            return ControllerResult("failed", "get_metadata_summary failed", tuple(results), service=request.service)
        if self._step(results, self._deps.append_boot_attempt, flash_ctx, AppendBootAttemptRequest(request.image_identity)) is None:
            return ControllerResult("failed", "append_boot_attempt failed", tuple(results), service=request.service)
        if request.confirm_app:
            if self._step(results, self._deps.append_app_confirmed, flash_ctx, AppendAppConfirmedRequest(request.image_identity)) is None:
                return ControllerResult("failed", "append_app_confirmed failed", tuple(results), service=request.service)
        if self._step(results, self._deps.run_flash_app, op_ctx, RunFlashAppRequest(request.entry_point)) is None:
            return ControllerResult("failed", "run_flash_app failed", tuple(results), service=request.service)
        return ControllerResult("ok", "run complete", tuple(results), service=request.service)

    @staticmethod
    def _cancelled(should_cancel: ShouldCancel | None) -> bool:
        return bool(should_cancel and should_cancel())

    @staticmethod
    def _step(results: list[Any], operation: Callable[..., Any], *args: Any) -> Any | None:
        result = operation(*args)
        results.append(result)
        if isinstance(result, OperationResult) and not result.ok:
            return None
        if hasattr(result, "ok") and not result.ok:
            return None
        return result

    @staticmethod
    def _same_image(image: Any, metadata_result: Any) -> bool:
        summary = getattr(metadata_result, "summary", metadata_result)
        if isinstance(summary, MetadataSummary):
            return compare_flash_image_with_metadata(image, summary).same_image
        if isinstance(summary, dict):
            if not summary.get("metadata_valid"):
                return False
            identity = image.identity
            return all(
                summary.get(name) == getattr(identity, name)
                for name in ("entry_point", "image_size_words", "image_crc32")
            )
        return compare_flash_image_with_metadata(image, summary).same_image
