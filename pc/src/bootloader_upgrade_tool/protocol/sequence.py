"""PC request-sequence allocation and response matching."""


class SequenceMismatchError(ValueError):
    pass


def next_sequence(previous: int) -> int:
    """Return the next nonzero uint16 request sequence."""

    if previous < 0 or previous > 0xFFFF:
        raise ValueError("previous sequence must fit uint16")
    return 1 if previous in (0, 0xFFFF) else previous + 1


def validate_response_sequence(request_sequence: int, response_sequence: int) -> None:
    if request_sequence == 0 or request_sequence > 0xFFFF:
        raise ValueError("request sequence must be in range 1..65535")
    if response_sequence != request_sequence:
        raise SequenceMismatchError(
            f"response sequence {response_sequence} does not match request {request_sequence}"
        )

