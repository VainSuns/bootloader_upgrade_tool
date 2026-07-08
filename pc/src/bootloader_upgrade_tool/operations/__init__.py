"""Public PC operation library API."""

from .context import FlashOperationContext, OperationContext, ProgressCallback
from .execution_ops import (
    BootCpu2ResetCpu1Request,
    BootCpu2RunCpu1Request,
    ResetTargetRequest,
    RunFlashAppRequest,
    RunRamImageRequest,
    boot_cpu2_reset_cpu1,
    boot_cpu2_run_cpu1,
    reset_target,
    run_flash_app,
    run_ram_image,
)
from .flash_ops import (
    EraseFlashImageAreaRequest,
    EraseSectorMaskRequest,
    ProgramFlashImageRequest,
    VerifyFlashImageRequest,
    erase_flash_image_area,
    erase_sector_mask,
    program_flash_image,
    verify_flash_image,
)
from .metadata_ops import (
    AppendAppConfirmedRequest,
    AppendBootAttemptRequest,
    AppendImageValidRequest,
    append_app_confirmed,
    append_boot_attempt,
    append_image_valid,
)
from .ram_ops import CheckRamCrcRequest, LoadRamImageRequest, check_ram_crc, load_ram_image
from .results import OperationErrorInfo, OperationResult, ProgressEvent, operation_result_to_dict
from .status_ops import get_device_info, get_last_error, get_metadata_summary, get_protocol_info

__all__ = [
    "AppendAppConfirmedRequest",
    "AppendBootAttemptRequest",
    "AppendImageValidRequest",
    "BootCpu2ResetCpu1Request",
    "BootCpu2RunCpu1Request",
    "CheckRamCrcRequest",
    "EraseFlashImageAreaRequest",
    "EraseSectorMaskRequest",
    "FlashOperationContext",
    "LoadRamImageRequest",
    "OperationContext",
    "OperationErrorInfo",
    "OperationResult",
    "ProgramFlashImageRequest",
    "ProgressCallback",
    "ProgressEvent",
    "ResetTargetRequest",
    "RunFlashAppRequest",
    "RunRamImageRequest",
    "VerifyFlashImageRequest",
    "append_app_confirmed",
    "append_boot_attempt",
    "append_image_valid",
    "boot_cpu2_reset_cpu1",
    "boot_cpu2_run_cpu1",
    "check_ram_crc",
    "erase_flash_image_area",
    "erase_sector_mask",
    "get_device_info",
    "get_last_error",
    "get_metadata_summary",
    "get_protocol_info",
    "load_ram_image",
    "operation_result_to_dict",
    "program_flash_image",
    "reset_target",
    "run_flash_app",
    "run_ram_image",
    "verify_flash_image",
]
