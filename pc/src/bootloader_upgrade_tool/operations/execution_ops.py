"""Run and reset operations."""

from __future__ import annotations

from dataclasses import dataclass

from ..protocol.constants import Target
from ..protocol.models import split_u32
from .context import OperationContext
from .results import failure_result, ok_result, transact


@dataclass(frozen=True)
class RunFlashAppRequest:
    entry_point: int


@dataclass(frozen=True)
class RunRamImageRequest:
    entry_point: int

    def __post_init__(self) -> None:
        if type(self.entry_point) is not int or self.entry_point < 0:
            raise ValueError("entry_point must be a non-negative integer")


@dataclass(frozen=True)
class ResetTargetRequest:
    pass


@dataclass(frozen=True)
class BootCpu2RunCpu1Request:
    pass


@dataclass(frozen=True)
class BootCpu2ResetCpu1Request:
    pass


def run_flash_app(ctx: OperationContext, request: RunFlashAppRequest):
    operation = "run_flash_app"
    try:
        transact(ctx, "run", (int(Target.FLASH_APP), *split_u32(request.entry_point), 0), stage="RUN")
        return ok_result(ctx, operation, "RUN", {"entry_point": request.entry_point})
    except Exception as exc:
        return failure_result(ctx, operation, "RUN", exc)


def run_ram_image(ctx: OperationContext, request: RunRamImageRequest):
    operation = "run_ram_image"
    try:
        transact(ctx, "run_ram", (*split_u32(request.entry_point), 0), stage="RUN_RAM")
        return ok_result(ctx, operation, "RUN_RAM", {"entry_point": request.entry_point})
    except Exception as exc:
        return failure_result(ctx, operation, "RUN_RAM", exc)


def reset_target(ctx: OperationContext, request: ResetTargetRequest):
    operation = "reset_target"
    try:
        transact(ctx, "reset", stage="RESET")
        return ok_result(ctx, operation, "RESET", {})
    except Exception as exc:
        return failure_result(ctx, operation, "RESET", exc)


def boot_cpu2_run_cpu1(ctx: OperationContext, request: BootCpu2RunCpu1Request):
    operation = "boot_cpu2_run_cpu1"
    try:
        transact(ctx, "boot_cpu2_run_cpu1", stage="BOOT_CPU2_RUN_CPU1")
        return ok_result(ctx, operation, "BOOT_CPU2_RUN_CPU1", {})
    except Exception as exc:
        return failure_result(ctx, operation, "BOOT_CPU2_RUN_CPU1", exc)


def boot_cpu2_reset_cpu1(ctx: OperationContext, request: BootCpu2ResetCpu1Request):
    operation = "boot_cpu2_reset_cpu1"
    try:
        transact(ctx, "boot_cpu2_reset_cpu1", stage="BOOT_CPU2_RESET_CPU1")
        return ok_result(ctx, operation, "BOOT_CPU2_RESET_CPU1", {})
    except Exception as exc:
        return failure_result(ctx, operation, "BOOT_CPU2_RESET_CPU1", exc)
