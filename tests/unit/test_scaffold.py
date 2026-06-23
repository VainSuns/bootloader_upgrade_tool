from bootloader_upgrade_tool import __version__
from bootloader_upgrade_tool.protocol.constants import (
    HEADER_WORDS,
    MAGIC0,
    MAGIC1,
    WRITE_DATA_ALIGNMENT_WORDS,
    WRITE_DATA_PAD_WORD,
)


def test_package_and_framing_scaffold() -> None:
    assert __version__ == "0.0.0"
    assert (MAGIC0, MAGIC1) == (0xA55A, 0x5AA5)
    assert HEADER_WORDS == 10
    assert WRITE_DATA_ALIGNMENT_WORDS == 8
    assert WRITE_DATA_PAD_WORD == 0xFFFF
