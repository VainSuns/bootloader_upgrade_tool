from bootloader_upgrade_tool.gui.serial_ports import SystemSerialPortProvider


class _Port:
    device = "COM3"
    name = "COM3"
    description = "FTDI USB Serial Port"
    hwid = "USB VID:PID=0403:6015 SER=abc"
    manufacturer = "FTDI"
    product = "USB Serial Port"
    serial_number = "abc"
    vid = 0x0403
    pid = 0x6015


def test_production_provider_is_lazy_and_compact(monkeypatch):
    calls = []
    import serial.tools.list_ports

    monkeypatch.setattr(serial.tools.list_ports, "comports", lambda: calls.append(True) or [_Port(), _Port()])
    provider = SystemSerialPortProvider()
    assert calls == []
    ports = provider.list_ports()
    assert len(ports) == 1
    assert ports[0].device == "COM3"
    assert ports[0].display_name == "COM3 - FTDI"
    assert "USB VID:PID" in ports[0].tooltip


def test_provider_uses_adapter_identity_outside_description(monkeypatch):
    class Port(_Port):
        description = "USB Serial Port (COM3)"
        manufacturer = "FTDI International"

    import serial.tools.list_ports
    monkeypatch.setattr(serial.tools.list_ports, "comports", lambda: [Port()])
    assert SystemSerialPortProvider().list_ports()[0].display_name == "COM3 - FTDI"


def test_provider_shortens_unknown_visible_description_but_keeps_tooltip(monkeypatch):
    original = "A very long custom serial adapter description that should remain available"

    class Port(_Port):
        description = original
        manufacturer = ""
        product = ""
        hwid = "CUSTOM"

    import serial.tools.list_ports
    monkeypatch.setattr(serial.tools.list_ports, "comports", lambda: [Port()])
    port = SystemSerialPortProvider().list_ports()[0]
    assert len(port.display_name.removeprefix("COM3 - ")) <= 28
    assert original in port.tooltip
