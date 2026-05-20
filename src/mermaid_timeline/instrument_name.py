"""Internal helpers for canonical MERMAID instrument serial names."""

from __future__ import annotations

from dataclasses import dataclass
import re

_SERIAL_RE = re.compile(
    r"^(?P<kinst>\d+\.\d+)-(?P<instrument_code>[A-Z]+)-(?P<instrument_number>\d+)$"
)


@dataclass(frozen=True, slots=True)
class InstrumentName:
    serial: str
    kinst: str
    instrument_code: str
    instrument_number: str
    instrument_id: str


def parse_instrument_name(serial: str) -> InstrumentName:
    """Parse one canonical instrument serial directory name."""

    match = _SERIAL_RE.fullmatch(serial)
    if match is None:
        raise ValueError(f"unsupported instrument serial name: {serial}")

    kinst = match.group("kinst")
    instrument_code = match.group("instrument_code")
    instrument_number = match.group("instrument_number")
    padded_number = instrument_number.zfill(5 - len(instrument_code))
    instrument_id = f"{instrument_code}{padded_number}"
    if len(instrument_id) > 5:
        raise ValueError(
            f"instrument code and number exceed 5-character station limit: {serial}"
        )

    return InstrumentName(
        serial=serial,
        kinst=kinst,
        instrument_code=instrument_code,
        instrument_number=instrument_number,
        instrument_id=instrument_id,
    )


def maybe_parse_instrument_name(serial: str) -> InstrumentName | None:
    """Parse one instrument serial directory name when it is canonical."""

    try:
        return parse_instrument_name(serial)
    except ValueError:
        return None
