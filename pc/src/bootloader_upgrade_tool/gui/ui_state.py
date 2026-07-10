"""Dynamic-property contract shared by Phase 11 GUI widgets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from PySide6.QtWidgets import QWidget

UI_ROLES: Final = frozenset(
    {
        "page",
        "pageTitle",
        "pageDescription",
        "card",
        "cardHeader",
        "cardTitle",
        "sectionTitle",
        "fieldLabel",
        "valueLabel",
        "helperText",
        "codeText",
        "ribbonGroup",
        "statusDot",
        "statusBadge",
        "scopeBadge",
        "banner",
        "separator",
        "emptyState",
        "consolePanel",
    }
)

UI_VARIANTS: Final = frozenset(
    {
        "primary",
        "secondary",
        "ghost",
        "ribbon",
        "toolbar",
        "consoleTool",
        "danger",
        "dangerGhost",
        "link",
    }
)

UI_STATES: Final = frozenset(
    {
        "neutral",
        "idle",
        "unknown",
        "disconnected",
        "connecting",
        "connected",
        "busy",
        "success",
        "warning",
        "error",
        "dirty",
        "clean",
        "protected",
        "unavailable",
    }
)

UI_LEVELS: Final = frozenset(
    {"debug", "info", "warning", "error", "success", "protocol"}
)
UI_SCOPES: Final = frozenset({"current", "global"})

_PROPERTY_VALUES: Final[Mapping[str, frozenset[str]]] = {
    "uiRole": UI_ROLES,
    "variant": UI_VARIANTS,
    "state": UI_STATES,
    "level": UI_LEVELS,
    "scope": UI_SCOPES,
}


def validate_ui_property(name: str, value: object) -> None:
    """Validate one frozen dynamic property before applying it."""

    allowed = _PROPERTY_VALUES.get(name)
    if allowed is None:
        raise ValueError(f"unsupported GUI dynamic property: {name!r}")
    if not isinstance(value, str) or value not in allowed:
        rendered = ", ".join(sorted(allowed))
        raise ValueError(
            f"invalid {name} value {value!r}; expected one of: {rendered}"
        )


def set_ui_properties(widget: QWidget, **properties: object) -> bool:
    """Apply validated properties and repolish only when a value changes."""

    if not isinstance(widget, QWidget):
        raise TypeError("widget must be a QWidget")

    for name, value in properties.items():
        validate_ui_property(name, value)

    changed = False
    for name, value in properties.items():
        if widget.property(name) != value:
            widget.setProperty(name, value)
            changed = True

    if not changed:
        return False

    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()
    return True


def set_ui_role(widget: QWidget, value: str) -> bool:
    return set_ui_properties(widget, uiRole=value)


def set_ui_variant(widget: QWidget, value: str) -> bool:
    return set_ui_properties(widget, variant=value)


def set_ui_state(widget: QWidget, value: str) -> bool:
    return set_ui_properties(widget, state=value)


def set_ui_level(widget: QWidget, value: str) -> bool:
    return set_ui_properties(widget, level=value)


def set_ui_scope(widget: QWidget, value: str) -> bool:
    return set_ui_properties(widget, scope=value)
