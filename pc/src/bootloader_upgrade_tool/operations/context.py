"""Operation context objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..images.models import PreparedServiceImage
from ..session import UpgradeSession
from ..targets import TargetProfile
from .results import ProgressEvent


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass
class OperationContext:
    session: UpgradeSession
    target: TargetProfile
    progress: ProgressCallback | None = None


@dataclass(kw_only=True)
class FlashOperationContext(OperationContext):
    service: PreparedServiceImage
    force_service_attach: bool = False
