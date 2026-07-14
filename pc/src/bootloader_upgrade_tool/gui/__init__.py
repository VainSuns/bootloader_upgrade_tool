__all__ = [
    "BootloaderMainWindow",
    "MainWindow",
    "ProgramImageBinding",
    "AdvancedReadOnlyBinding",
    "CpuProgramStatusBinding",
    "PrepareFlashImageRequest",
    "PreparedImageSummary",
    "SourceFileFingerprint",
    "ImageSourceKind",
    "Hex2000Source",
    "StatusRequest",
    "MetadataRefreshRequest",
    "DeviceInfoRequest",
    "ProtocolInfoRequest",
    "LastErrorRequest",
    "MetadataStatusSnapshot",
    "DeviceInfoStatusSnapshot",
    "ProtocolInfoStatusSnapshot",
    "LastErrorStatusSnapshot",
    "LoadedImageMatch",
    "MetadataScanState",
    "operation_progress_to_task_update",
    "operation_result_to_task_result",
    "main",
    "run",
]


def __getattr__(name: str):
    if name in {"operation_progress_to_task_update", "operation_result_to_task_result"}:
        from .operation_task_adapter import (
            operation_progress_to_task_update,
            operation_result_to_task_result,
        )

        return locals()[name]
    if name in {"main", "run"}:
        from .app import main

        return main
    if name in {"BootloaderMainWindow", "MainWindow"}:
        from .main_window import BootloaderMainWindow

        return BootloaderMainWindow
    if name == "ProgramImageBinding":
        from .program_image_binding import ProgramImageBinding

        return ProgramImageBinding
    if name == "AdvancedReadOnlyBinding":
        from .advanced_read_binding import AdvancedReadOnlyBinding

        return AdvancedReadOnlyBinding
    if name == "CpuProgramStatusBinding":
        from .cpu_program_status_binding import CpuProgramStatusBinding

        return CpuProgramStatusBinding
    if name in {
        "PrepareFlashImageRequest",
        "PreparedImageSummary",
        "SourceFileFingerprint",
        "ImageSourceKind",
        "Hex2000Source",
    }:
        from .image_preparation_models import (
            Hex2000Source,
            ImageSourceKind,
            PrepareFlashImageRequest,
            PreparedImageSummary,
            SourceFileFingerprint,
        )

        return locals()[name]
    if name in {
        "StatusRequest",
        "MetadataRefreshRequest",
        "DeviceInfoRequest",
        "ProtocolInfoRequest",
        "LastErrorRequest",
        "MetadataStatusSnapshot",
        "DeviceInfoStatusSnapshot",
        "ProtocolInfoStatusSnapshot",
        "LastErrorStatusSnapshot",
        "LoadedImageMatch",
        "MetadataScanState",
    }:
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

        return locals()[name]
    raise AttributeError(name)
