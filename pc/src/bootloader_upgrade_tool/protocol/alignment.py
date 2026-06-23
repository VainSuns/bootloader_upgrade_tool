"""Protocol-level write-data alignment validation and PC-side padding."""

from collections.abc import Sequence

from .constants import WRITE_DATA_ALIGNMENT_WORDS, WRITE_DATA_PAD_WORD


class DataAlignmentError(ValueError):
    pass


def validate_write_data(words: Sequence[int], *, max_data_words: int | None = None) -> None:
    count = len(words)
    if count == 0:
        raise DataAlignmentError("write data must not be empty")
    if count % WRITE_DATA_ALIGNMENT_WORDS:
        raise DataAlignmentError("write data word count must be a multiple of 8")
    if max_data_words is not None:
        if max_data_words <= 0 or max_data_words % WRITE_DATA_ALIGNMENT_WORDS:
            raise ValueError("max_data_words must be a positive multiple of 8")
        if count > max_data_words:
            raise DataAlignmentError("write data exceeds max_data_words")
    if any(word < 0 or word > 0xFFFF for word in words):
        raise ValueError("write data values must fit uint16")


def pad_write_data(words: Sequence[int], *, max_data_words: int | None = None) -> tuple[int, ...]:
    if not words:
        raise DataAlignmentError("write data must not be empty")
    if any(word < 0 or word > 0xFFFF for word in words):
        raise ValueError("write data values must fit uint16")
    missing = (-len(words)) % WRITE_DATA_ALIGNMENT_WORDS
    result = tuple(words) + (WRITE_DATA_PAD_WORD,) * missing
    validate_write_data(result, max_data_words=max_data_words)
    return result

