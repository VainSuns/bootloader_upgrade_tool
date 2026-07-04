"""Transport-independent protocol primitives."""

from .alignment import DataAlignmentError, pad_write_data, validate_write_data
from .constants import Command, PacketType, Status
from .crc import crc16_ccitt_false, crc16_words, words_to_little_endian_bytes
from .frame import (
    Frame,
    FrameError,
    FrameLengthError,
    HeaderCrcError,
    PayloadCrcError,
    decode_frame,
)
from .models import DeviceInfo, ErrorDetail, ServiceStatus, join_u32, split_u32
from .resync import ResyncReader
from .sequence import SequenceMismatchError, next_sequence, validate_response_sequence

__all__ = [
    "Command",
    "DataAlignmentError",
    "DeviceInfo",
    "ErrorDetail",
    "Frame",
    "FrameError",
    "FrameLengthError",
    "HeaderCrcError",
    "PacketType",
    "PayloadCrcError",
    "ResyncReader",
    "SequenceMismatchError",
    "ServiceStatus",
    "Status",
    "crc16_ccitt_false",
    "crc16_words",
    "decode_frame",
    "join_u32",
    "next_sequence",
    "pad_write_data",
    "split_u32",
    "validate_write_data",
    "validate_response_sequence",
    "words_to_little_endian_bytes",
]
