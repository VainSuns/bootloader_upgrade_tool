import pytest

from bootloader_upgrade_tool.protocol import (
    DataAlignmentError,
    DeviceInfo,
    ErrorDetail,
    Frame,
    FrameLengthError,
    HeaderCrcError,
    PacketType,
    PayloadCrcError,
    ResyncReader,
    crc16_ccitt_false,
    crc16_words,
    decode_frame,
    next_sequence,
    pad_write_data,
    validate_write_data,
    validate_response_sequence,
)
from bootloader_upgrade_tool.protocol.constants import Command, Feature, Status
from bootloader_upgrade_tool.protocol.sequence import SequenceMismatchError


def test_crc_standard_check_and_empty_payload() -> None:
    assert crc16_ccitt_false(b"123456789") == 0x29B1
    assert crc16_ccitt_false(b"") == 0xFFFF
    assert crc16_words(()) == 0xFFFF
    assert crc16_words((0xA55A,)) == crc16_ccitt_false(bytes((0x5A, 0xA5)))


def test_frame_round_trip_and_golden_layout() -> None:
    frame = Frame(PacketType.REQUEST, Command.PING, 1, (0x1234, 0xABCD))
    words = frame.encode_words()

    assert words == (
        0xA55A,
        0x5AA5,
        0x0001,
        0x0001,
        0x0001,
        0x0001,
        0x0000,
        0x0000,
        0x0002,
        0x8CEB,
        0x1234,
        0xABCD,
        0x2B52,
    )
    assert decode_frame(words) == frame
    assert frame.encode_bytes()[:4] == bytes((0x5A, 0xA5, 0xA5, 0x5A))


def test_frame_validates_crc_length_and_reserved_sequence() -> None:
    words = list(Frame(PacketType.RESPONSE, Command.PING, 4).encode_words())
    bad_header = words.copy()
    bad_header[4] ^= 1
    with pytest.raises(HeaderCrcError):
        decode_frame(bad_header)

    bad_payload = list(Frame(PacketType.RESPONSE, Command.PING, 4, (1,)).encode_words())
    bad_payload[-1] ^= 1
    with pytest.raises(PayloadCrcError):
        decode_frame(bad_payload)
    with pytest.raises(FrameLengthError):
        decode_frame(words + [0])
    with pytest.raises(ValueError, match="reserved"):
        Frame(PacketType.REQUEST, Command.PING, 0)


def test_sequence_wrap_and_response_matching() -> None:
    assert next_sequence(0) == 1
    assert next_sequence(1) == 2
    assert next_sequence(0xFFFF) == 1
    validate_response_sequence(8, 8)
    with pytest.raises(SequenceMismatchError):
        validate_response_sequence(8, 9)


def test_resync_reader_handles_noise_bad_header_and_chunking() -> None:
    first = Frame(PacketType.RESPONSE, Command.PING, 1, (7,)).encode_words()
    damaged = list(Frame(PacketType.RESPONSE, Command.PING, 2).encode_words())
    damaged[9] ^= 1
    second = Frame(PacketType.RESPONSE, Command.GET_DEVICE_INFO, 3, (8,)).encode_words()
    stream = [0x9999, 0xA55A, 0x1111, *first, *damaged, *second]
    reader = ResyncReader(max_payload_words=16)

    assert reader.feed(stream[:8]) == []
    frames = reader.feed(stream[8:])

    assert [frame.sequence for frame in frames] == [1, 3]
    assert reader.errors


def test_resync_reader_consumes_bad_payload_and_continues() -> None:
    bad = list(Frame(PacketType.RESPONSE, Command.PING, 1, (7,)).encode_words())
    bad[-1] ^= 1
    good = Frame(PacketType.RESPONSE, Command.PING, 2).encode_words()
    reader = ResyncReader(max_payload_words=8)

    assert reader.feed([*bad, *good]) == [decode_frame(good)]
    assert isinstance(reader.errors[0], PayloadCrcError)


def test_device_info_round_trip_and_alignment_guard() -> None:
    info = DeviceInfo(
        0x377D,
        1,
        1,
        2,
        3,
        1,
        int(Feature.ERASE | Feature.PROGRAM),
        256,
        128,
        2,
        1,
    )
    assert DeviceInfo.from_words(info.to_words()) == info
    with pytest.raises(ValueError, match="multiple of 8"):
        DeviceInfo(0x377D, 1, 1, 0, 0, 1, 0, 256, 127, 2, 1)


def test_error_detail_round_trip() -> None:
    detail = ErrorDetail(3, 4, 0x12345678, 0x00010002, 9, 0xABCDEF01, 5, 6)
    assert ErrorDetail.from_words(detail.to_words()) == detail


def test_write_data_padding_validation_and_maximum() -> None:
    assert pad_write_data((1, 2, 3)) == (1, 2, 3, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF)
    validate_write_data(tuple(range(8)), max_data_words=8)
    with pytest.raises(DataAlignmentError, match="empty"):
        pad_write_data(())
    with pytest.raises(DataAlignmentError, match="multiple of 8"):
        validate_write_data((1,))
    with pytest.raises(DataAlignmentError, match="exceeds"):
        pad_write_data(tuple(range(9)), max_data_words=8)


def test_protocol_has_no_ack_nak_or_timeout_status() -> None:
    assert "ACK" not in PacketType.__members__
    assert "NAK" not in PacketType.__members__
    assert "TIMEOUT" not in Status.__members__
