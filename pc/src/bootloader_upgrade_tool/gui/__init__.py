__all__ = [
    "BootloaderMainWindow",
    "MainWindow",
    "ProgramImageBinding",
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
    "main",
    "run",
]


def __getattr__(name: str):
    if name in {"main", "run"}:
        from .app import main

        return main
    if name in {"BootloaderMainWindow", "MainWindow"}:
        from .main_window import BootloaderMainWindow

        return BootloaderMainWindow
    if name == "ProgramImageBinding":
        from .program_image_binding import ProgramImageBinding

        return ProgramImageBinding
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
    }:
        from .status_models import (
            DeviceInfoRequest,
            LastErrorRequest,
            MetadataRefreshRequest,
            ProtocolInfoRequest,
            StatusRequest,
        )

        return locals()[name]
    raise AttributeError(name)
