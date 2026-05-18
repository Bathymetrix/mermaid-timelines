"""Internal interval JSONL reader for reporting commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mermaid_timeline._time import parse_timestamp
from mermaid_timeline.pipeline import BUFFER_INTERVALS_FILE, DETREQ_INTERVALS_FILE
from mermaid_timeline.records import JsonObject, SourceRecord, iter_jsonl


@dataclass(frozen=True, slots=True)
class IntervalRow:
    instrument_id: str
    interval_type: str
    start_time: datetime
    end_time: datetime | None
    start_time_text: str
    end_time_text: str | None
    start_boundary: str
    end_boundary: str
    provenance: JsonObject
    interval_file: Path
    interval_line: int


def read_interval_rows(input_root: Path) -> list[IntervalRow]:
    """Read timeline interval products below an output root."""

    root = input_root.resolve()
    intervals: list[IntervalRow] = []
    for filename in (BUFFER_INTERVALS_FILE, DETREQ_INTERVALS_FILE):
        for path in sorted(root.rglob(filename)):
            intervals.extend(_read_file(path))
    intervals.sort(
        key=lambda row: (
            row.instrument_id,
            row.start_time,
            row.interval_type,
            row.interval_line,
        )
    )
    return intervals


def _read_file(path: Path) -> list[IntervalRow]:
    return [_interval_from_record(path, record) for record in iter_jsonl(path)]


def _interval_from_record(path: Path, record: SourceRecord) -> IntervalRow:
    row = record.row
    instrument_id = _required_string(row, "instrument_id", path, record.line_number)
    interval_type = _required_string(row, "interval_type", path, record.line_number)
    start_time_text = _required_string(row, "start_time", path, record.line_number)
    start_boundary = _required_string(row, "start_boundary", path, record.line_number)
    end_boundary = _required_string(row, "end_boundary", path, record.line_number)

    start_time = _parse_time(start_time_text, "start_time", path, record.line_number)
    end_time_value = row.get("end_time")
    end_time_text = None if end_time_value is None else str(end_time_value)
    end_time = (
        None
        if end_time_value is None
        else _parse_time(end_time_value, "end_time", path, record.line_number)
    )

    provenance_value = row.get("provenance")
    if provenance_value is None:
        provenance: JsonObject = {}
    elif isinstance(provenance_value, dict):
        provenance = provenance_value
    else:
        raise ValueError(f"{path}:{record.line_number}: provenance must be an object")

    return IntervalRow(
        instrument_id=instrument_id,
        interval_type=interval_type,
        start_time=start_time,
        end_time=end_time,
        start_time_text=start_time_text,
        end_time_text=end_time_text,
        start_boundary=start_boundary,
        end_boundary=end_boundary,
        provenance=provenance,
        interval_file=path,
        interval_line=record.line_number,
    )


def _required_string(
    row: JsonObject,
    field_name: str,
    path: Path,
    line_number: int,
) -> str:
    value = row.get(field_name)
    if value is None or str(value).strip() == "":
        raise ValueError(f"{path}:{line_number}: {field_name} is required")
    return str(value)


def _parse_time(
    value: object,
    field_name: str,
    path: Path,
    line_number: int,
) -> datetime:
    try:
        return parse_timestamp(value, field_name=field_name)
    except ValueError as exc:
        raise ValueError(f"{path}:{line_number}: {exc}") from exc
