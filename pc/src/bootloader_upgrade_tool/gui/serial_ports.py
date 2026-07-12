"""Lazy COM-port enumeration and compact display formatting."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SerialPortInfo:
    device: str
    display_name: str
    tooltip: str


class SerialPortProvider(Protocol):
    def list_ports(self) -> tuple[SerialPortInfo, ...]: ...


class SystemSerialPortProvider:
    """Production provider; pyserial is imported only when refresh is requested."""

    def list_ports(self) -> tuple[SerialPortInfo, ...]:
        from serial.tools import list_ports

        ports: list[SerialPortInfo] = []
        seen: set[str] = set()
        for port in list_ports.comports():
            device = str(getattr(port, "device", ""))
            if not device or device.casefold() in seen:
                continue
            seen.add(device.casefold())
            display_name = device
            fields = {
                name: getattr(port, name, None)
                for name in (
                    "device",
                    "name",
                    "description",
                    "hwid",
                    "manufacturer",
                    "product",
                    "serial_number",
                    "location",
                    "interface",
                    "usb_device_path",
                    "vid",
                    "pid",
                )
            }
            tooltip = "\n".join(
                f"{name}: {value}"
                for name, value in fields.items()
                if value not in (None, "")
            )
            ports.append(SerialPortInfo(device, display_name, tooltip))
        return tuple(
            sorted(ports, key=lambda item: (item.device.casefold(), item.display_name.casefold()))
        )


ProductionSerialPortProvider = SystemSerialPortProvider


def _compact_description(
    description: str,
    manufacturer: str = "",
    product: str = "",
    hwid: str = "",
) -> str:
    fields = tuple(" ".join(value.split()) for value in (manufacturer, product, description, hwid))
    folded = " ".join(fields).casefold()
    if "ftdi" in folded:
        return "FTDI"
    if "ch340" in folded or "ch341" in folded or "usb-serial ch" in folded:
        return "CH340"
    if "cp210" in folded or "silicon labs" in folded:
        return "CP210x"
    if "prolific" in folded:
        return "Prolific"
    value = re.sub(r"\s*\(COM\d+\)\s*", " ", fields[2], flags=re.IGNORECASE).strip()
    value_folded = value.casefold()
    if value_folded == "usb serial port":
        return "USB Serial"
    if value_folded == "communications port":
        return "Serial"
    if not value:
        return ""
    return value if len(value) <= 28 else value[:27].rstrip() + "…"


__all__ = [
    "ProductionSerialPortProvider",
    "SerialPortInfo",
    "SerialPortProvider",
    "SystemSerialPortProvider",
]
