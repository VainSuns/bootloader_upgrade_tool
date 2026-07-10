"""Clearly labelled static placeholders used while page batches are pending."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from ..icon_manager import IconManager
from ..layout_metrics import PAGE_BLOCK_SPACING, PAGE_MARGINS
from ..navigation import PageId
from ..ui_state import set_ui_role
from ..widgets.card import NoticeBanner
from ..widgets.page_header import PageHeader


@dataclass(frozen=True, slots=True)
class PlaceholderPageSpec:
    """Frozen shell-only description for one registered page."""

    page_id: PageId
    title: str
    object_name: str
    implementation_batch: str


class PlaceholderPage(QFrame):
    """A non-functional page that explicitly identifies itself as a placeholder."""

    def __init__(
        self,
        spec: PlaceholderPageSpec,
        *,
        icon_manager: IconManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.page_id = spec.page_id
        self.spec = spec
        self.setObjectName(spec.object_name)
        self.setFrameShape(QFrame.Shape.NoFrame)
        set_ui_role(self, "page")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(PAGE_BLOCK_SPACING)

        self.header = PageHeader(
            spec.title,
            description="Phase 11 static shell",
            object_name=f"{spec.object_name}Header",
            parent=self,
        )
        layout.addWidget(self.header)

        self.notice = NoticeBanner(
            "Layout Placeholder",
            (
                f"This page is reserved for {spec.implementation_batch}. "
                "No session, transport, protocol, Flash, metadata, RUN, reset, "
                "CPU2 backend, or W5300 action is available here."
            ),
            state="warning",
            semantic_icon="common.information",
            icon_manager=icon_manager,
            object_name=f"{spec.object_name}PlaceholderBanner",
            parent=self,
        )
        layout.addWidget(self.notice)
        layout.addStretch(1)
