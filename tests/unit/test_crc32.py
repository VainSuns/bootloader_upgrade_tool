import shutil
import subprocess
from pathlib import Path

import pytest

from bootloader_upgrade_tool.firmware.crc32 import crc32_bytes, crc32_words


ROOT = Path(__file__).resolve().parents[2]


WORD_VECTORS = (
    ((), 0x00000000),
    ((0x0000,), 0x41D912FF),
    ((0xFFFF,), 0xFFFF0000),
    ((0x1234,), 0x094A9040),
    ((0x1234, 0x5678), 0x2441C0CB),
    ((0xA55A, 0x5AA5), 0x02895F17),
    (tuple(range(8)), 0xC815D9ED),
    ((0xFFFF,) * 8, 0x3FB3C61A),
    ((0x0001, 0x0203, 0x0405, 0x0607), 0xC3299525),
)


@pytest.mark.parametrize(("words", "expected"), WORD_VECTORS)
def test_crc32_word_vectors(words: tuple[int, ...], expected: int) -> None:
    assert crc32_words(words) == expected


def test_crc32_bytes_standard_reference() -> None:
    assert crc32_bytes(b"123456789") == 0xCBF43926


def test_crc32_words_are_low_byte_first() -> None:
    assert crc32_words((0x1234,)) == crc32_bytes(bytes((0x34, 0x12)))


@pytest.mark.parametrize("words", [(-1,), (0x10000,)])
def test_crc32_words_reject_out_of_range_values(words: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="uint16"):
        crc32_words(words)


def test_dsp_crc32_utility_matches_vectors(tmp_path: Path) -> None:
    gcc = shutil.which("gcc")
    if gcc is None:
        pytest.skip("GCC is not available for the optional DSP CRC32 host check")

    test_c = tmp_path / "test_boot_crc32.c"
    test_c.write_text(
        r'''
#include <assert.h>
#include <stdint.h>
#include "boot_crc32.h"

int main(void)
{
    const uint16_t empty = 0U;
    const uint16_t w0[] = {0x0000U};
    const uint16_t w1[] = {0xFFFFU};
    const uint16_t w2[] = {0x1234U};
    const uint16_t w3[] = {0x1234U, 0x5678U};
    const uint16_t w4[] = {0xA55AU, 0x5AA5U};
    const uint16_t w5[] = {0x0000U, 0x0001U, 0x0002U, 0x0003U, 0x0004U, 0x0005U, 0x0006U, 0x0007U};
    const uint16_t w6[] = {0xFFFFU, 0xFFFFU, 0xFFFFU, 0xFFFFU, 0xFFFFU, 0xFFFFU, 0xFFFFU, 0xFFFFU};
    const uint16_t w7[] = {0x0001U, 0x0203U, 0x0405U, 0x0607U};

    assert(BootCrc32_CalcWords(&empty, 0UL) == 0x00000000UL);
    assert(BootCrc32_CalcWords(w0, 1UL) == 0x41D912FFUL);
    assert(BootCrc32_CalcWords(w1, 1UL) == 0xFFFF0000UL);
    assert(BootCrc32_CalcWords(w2, 1UL) == 0x094A9040UL);
    assert(BootCrc32_CalcWords(w3, 2UL) == 0x2441C0CBUL);
    assert(BootCrc32_CalcWords(w4, 2UL) == 0x02895F17UL);
    assert(BootCrc32_CalcWords(w5, 8UL) == 0xC815D9EDUL);
    assert(BootCrc32_CalcWords(w6, 8UL) == 0x3FB3C61AUL);
    assert(BootCrc32_CalcWords(w7, 4UL) == 0xC3299525UL);
    assert(BootCrc32_UpdateWord(BOOT_CRC32_INIT_VALUE, 0x1234U) ==
           BootCrc32_UpdateByte(BootCrc32_UpdateByte(BOOT_CRC32_INIT_VALUE, 0x34U), 0x12U));
    return 0;
}
''',
        encoding="utf-8",
    )
    executable = tmp_path / "test_boot_crc32.exe"
    subprocess.run(
        [
            gcc,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{ROOT / 'dsp' / 'bootloader_common' / 'include'}",
            str(ROOT / "dsp" / "bootloader_common" / "src" / "boot_crc32.c"),
            str(test_c),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(executable)], check=True)
