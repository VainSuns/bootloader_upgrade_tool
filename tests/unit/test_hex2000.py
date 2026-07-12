from pathlib import Path
from subprocess import CompletedProcess

import pytest

from bootloader_upgrade_tool.firmware.hex2000 import (
    Hex2000ConfigurationError,
    Hex2000Error,
    Hex2000NotFoundError,
    Sci8ParseError,
    build_firmware_image,
    locate_hex2000,
    parse_sci8_file,
    parse_sci8_text,
    run_hex2000,
)


BOOT_WORDS = (
    0x08AA,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0x0008,
    0x1234,
    3,
    0x0008,
    0x0002,
    0x1111,
    0x2222,
    0x3333,
    2,
    0x0008,
    0x2000,
    0xAAAA,
    0xBBBB,
    0,
)


def _word_text() -> str:
    return "\n".join(f"{word:04X}" for word in BOOT_WORDS)


def _byte_text() -> str:
    return " ".join(f"{byte:02X}" for word in BOOT_WORDS for byte in (word & 0xFF, word >> 8))


@pytest.mark.parametrize("text", [_word_text(), _byte_text()])
def test_parse_sci8_word_and_little_endian_byte_forms(text: str) -> None:
    table = parse_sci8_text(text)

    assert table.entry_point == 0x00081234
    assert [block.address for block in table.blocks] == [0x00080002, 0x00082000]
    assert table.blocks[0].words == (0x1111, 0x2222, 0x3333)


@pytest.mark.parametrize(
    "words, message",
    [
        ((0x1234, *BOOT_WORDS[1:]), "unexpected SCI8 key"),
        (BOOT_WORDS[:-1], "terminator"),
        ((*BOOT_WORDS, 0x1234), "trailing data"),
    ],
)
def test_parse_sci8_rejects_malformed_tables(words: tuple[int, ...], message: str) -> None:
    with pytest.raises(Sci8ParseError, match=message):
        parse_sci8_text(" ".join(f"{word:04X}" for word in words))


def test_locate_hex2000_manual_then_environment(tmp_path) -> None:
    manual = tmp_path / "manual" / "hex2000.exe"
    environment = tmp_path / "compiler" / "bin" / "hex2000.exe"
    manual.parent.mkdir()
    environment.parent.mkdir(parents=True)
    manual.touch()
    environment.touch()

    assert locate_hex2000(manual, environ={"C2000_CG_ROOT": str(tmp_path / "compiler")}) == manual
    assert locate_hex2000(environ={"C2000_CG_ROOT": str(tmp_path / "compiler")}) == environment


def test_locate_hex2000_failure_explains_fallback() -> None:
    with pytest.raises(Hex2000NotFoundError, match="manual path or C2000_CG_ROOT"):
        locate_hex2000(environ={})


def test_hex2000_configuration_error_is_publicly_exported() -> None:
    from bootloader_upgrade_tool.firmware import Hex2000ConfigurationError as PublicError

    assert PublicError is Hex2000ConfigurationError


def test_invalid_explicit_path_does_not_fall_back(tmp_path) -> None:
    environment = tmp_path / "compiler" / "bin" / "hex2000.exe"
    environment.parent.mkdir(parents=True)
    environment.touch()

    with pytest.raises(Hex2000ConfigurationError):
        locate_hex2000(
            tmp_path / "missing.exe",
            environ={"C2000_CG_ROOT": str(tmp_path / "compiler")},
        )


def test_c2000_root_executable_and_old_environment_is_ignored(tmp_path) -> None:
    root_executable = tmp_path / "compiler" / "hex2000.exe"
    root_executable.parent.mkdir()
    root_executable.touch()

    assert locate_hex2000(environ={"C2000_CG_ROOT": str(root_executable.parent)}) == root_executable
    with pytest.raises(Hex2000NotFoundError):
        locate_hex2000(environ={"C200_CG_ROOT": str(root_executable.parent)})


def test_file_parsers_report_non_ascii_as_sci8_error(tmp_path) -> None:
    source = tmp_path / "bad.txt"
    source.write_bytes(b"\xff\xfe")

    with pytest.raises(Sci8ParseError, match="not ASCII"):
        parse_sci8_file(source)
    with pytest.raises(Sci8ParseError, match="not ASCII"):
        build_firmware_image(source, source)


def test_phase6_and_phase7_helpers_use_c2000_environment_name() -> None:
    tests_root = Path(__file__).resolve().parents[1]
    for relative in (
        "phase6/phase6_3_out_hex2000_workflow_test.py",
        "phase7/phase7_1_run_app_test.py",
    ):
        source = (tests_root / relative).read_text(encoding="utf-8")
        assert '{"C2000_CG_ROOT": c2000_cg_root}' in source
        assert '{"C200_CG_ROOT":' not in source
        assert '"--c2000-cg-root"' in source


def test_run_hex2000_uses_required_flags(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "hex2000.exe"
    source = tmp_path / "app.out"
    output = tmp_path / "app.txt"
    executable.touch()
    source.touch()
    observed: list[str] = []

    def fake_run(command, **kwargs):
        observed.extend(command)
        output.write_text(_word_text(), encoding="ascii")
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert run_hex2000(source, output, hex2000_path=executable) == output
    assert observed[1:6] == ["-boot", "-a", "-sci8", "-o", str(output)]


def test_run_hex2000_surfaces_tool_failure(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "hex2000.exe"
    source = tmp_path / "app.out"
    executable.touch()
    source.touch()
    monkeypatch.setattr(
        "subprocess.run",
        lambda command, **kwargs: CompletedProcess(command, 2, "", "bad input"),
    )
    with pytest.raises(Hex2000Error, match="bad input"):
        run_hex2000(source, tmp_path / "app.txt", hex2000_path=executable)


def test_build_firmware_image(tmp_path) -> None:
    generated = tmp_path / "app.txt"
    generated.write_text(_word_text(), encoding="ascii")

    image = build_firmware_image(Path("app.out"), generated)

    assert image.entry_point == 0x00081234
    assert image.total_words == 5
    assert len(image.file_checksum) == 64
    assert image.format_info["key"] == 0x08AA
