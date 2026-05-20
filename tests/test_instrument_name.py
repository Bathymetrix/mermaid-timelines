from __future__ import annotations

import pytest

from mermaid_timeline.instrument_name import parse_instrument_name


def test_parse_instrument_name_splits_serial_into_kinst_and_station() -> None:
    parsed = parse_instrument_name("467.174-T-0100")

    assert parsed.serial == "467.174-T-0100"
    assert parsed.kinst == "467.174"
    assert parsed.instrument_code == "T"
    assert parsed.instrument_number == "0100"
    assert parsed.instrument_id == "T0100"


def test_parse_instrument_name_pads_station_number_to_five_characters() -> None:
    parsed = parse_instrument_name("452.020-P-08")

    assert parsed.instrument_id == "P0008"


def test_parse_instrument_name_rejects_overlong_station_name() -> None:
    with pytest.raises(ValueError, match="5-character station"):
        parse_instrument_name("452.020-TOOL-0008")
