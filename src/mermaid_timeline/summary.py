"""Summarize interval durations into calendar bins."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from mermaid_timeline._time import format_timestamp, parse_timestamp
from mermaid_timeline.records import JsonObject, SourceRecords, iter_jsonl
from mermaid_timeline.schema import SCHEMA_VERSION, IntervalType, generated_by

BIN_SIZES = ("day", "week", "month", "year")
INTERVAL_TYPES: tuple[IntervalType, ...] = ("buf", "det", "req")
BINNING_POLICY = "clip_intervals_to_half_open_bins"
OVERLAP_POLICY = "sum_durations_without_unioning_by_interval_type"
SUMMARY_NUMERIC_PRECISION = 6


@dataclass(slots=True)
class _BinTotals:
    duration_seconds: dict[IntervalType, float] = field(
        default_factory=lambda: {interval_type: 0.0 for interval_type in INTERVAL_TYPES}
    )
    interval_count: dict[IntervalType, int] = field(
        default_factory=lambda: {interval_type: 0 for interval_type in INTERVAL_TYPES}
    )


type _BinKey = tuple[str, str | None, str, datetime]


def build_summary_intervals_from_files(
    paths: list[Path],
    *,
    default_instrument_serial: str | None = None,
) -> list[JsonObject]:
    """Build summary rows from existing interval JSONL files."""

    records = [record for path in paths if path.exists() for record in iter_jsonl(path)]
    return build_summary_intervals(
        records, default_instrument_serial=default_instrument_serial
    )


def build_summary_intervals(
    records: SourceRecords,
    *,
    default_instrument_serial: str | None = None,
) -> list[JsonObject]:
    totals: defaultdict[_BinKey, _BinTotals] = defaultdict(_BinTotals)

    for record in records:
        row = record.row
        interval_type = _interval_type(row)
        if interval_type is None:
            continue
        start_time = parse_timestamp(row.get("start_time"), field_name="start_time")
        end_value = row.get("end_time")
        if end_value is None:
            continue
        end_time = parse_timestamp(end_value, field_name="end_time")
        if end_time <= start_time:
            continue

        instrument_id = _required_text(row.get("instrument_id"), "instrument_id")
        instrument_serial = (
            _instrument_serial_from_row(row) or default_instrument_serial
        )

        for bin_size in BIN_SIZES:
            for bin_start, bin_end in _overlapping_bins(start_time, end_time, bin_size):
                overlap_start = max(start_time, bin_start)
                overlap_end = min(end_time, bin_end)
                overlap_seconds = (overlap_end - overlap_start).total_seconds()
                if overlap_seconds <= 0:
                    continue
                key = (instrument_id, instrument_serial, bin_size, bin_start)
                totals[key].duration_seconds[interval_type] += overlap_seconds
                totals[key].interval_count[interval_type] += 1

    return [
        _summary_row(key, bin_totals)
        for key, bin_totals in sorted(totals.items(), key=_sort_key)
    ]


def write_summary_jsonl(path: Path, rows: Iterable[JsonObject]) -> int:
    """Write summary rows with stable fixed-precision numeric durations."""

    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_summary_json_dumps(row))
            handle.write("\n")
            count += 1
    return count


def _summary_row(key: _BinKey, totals: _BinTotals) -> JsonObject:
    instrument_id, instrument_serial, bin_size, bin_start = key
    bin_end = _next_bin_start(bin_start, bin_size)
    bin_duration_seconds = (bin_end - bin_start).total_seconds()
    duration_seconds = {
        interval_type: _round_summary_number(totals.duration_seconds[interval_type])
        for interval_type in INTERVAL_TYPES
    }
    interval_count = {
        interval_type: totals.interval_count[interval_type]
        for interval_type in INTERVAL_TYPES
    }
    duration_fraction = {
        interval_type: _round_summary_number(
            totals.duration_seconds[interval_type] / bin_duration_seconds
        )
        for interval_type in INTERVAL_TYPES
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": generated_by(),
        "instrument_id": instrument_id,
        "instrument_serial": instrument_serial,
        "bin_size": bin_size,
        "bin_start_time": format_timestamp(bin_start),
        "bin_end_time": format_timestamp(bin_end),
        "duration_seconds": duration_seconds,
        "interval_count": interval_count,
        "duration_fraction": duration_fraction,
        "binning_policy": BINNING_POLICY,
        "overlap_policy": OVERLAP_POLICY,
    }


def _round_summary_number(value: float) -> float:
    return round(value, SUMMARY_NUMERIC_PRECISION)


def _summary_json_dumps(value: object) -> str:
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                f"{json.dumps(key, ensure_ascii=True)}:{_summary_json_dumps(item)}"
                for key, item in value.items()
            )
            + "}"
        )
    if isinstance(value, list):
        return "[" + ",".join(_summary_json_dumps(item) for item in value) + "]"
    if isinstance(value, float):
        return format(value, f".{SUMMARY_NUMERIC_PRECISION}f")
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _overlapping_bins(
    start_time: datetime, end_time: datetime, bin_size: str
) -> list[tuple[datetime, datetime]]:
    bins: list[tuple[datetime, datetime]] = []
    bin_start = _bin_start(start_time, bin_size)
    while bin_start < end_time:
        bin_end = _next_bin_start(bin_start, bin_size)
        if bin_end > start_time:
            bins.append((bin_start, bin_end))
        bin_start = bin_end
    return bins


def _bin_start(value: datetime, bin_size: str) -> datetime:
    value = value.astimezone(timezone.utc)
    if bin_size == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    if bin_size == "week":
        day_start = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start - timedelta(days=day_start.weekday())
    if bin_size == "month":
        return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if bin_size == "year":
        return value.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    raise ValueError(f"unsupported bin_size: {bin_size!r}")


def _next_bin_start(value: datetime, bin_size: str) -> datetime:
    if bin_size == "day":
        return value + timedelta(days=1)
    if bin_size == "week":
        return value + timedelta(weeks=1)
    if bin_size == "month":
        if value.month == 12:
            return value.replace(year=value.year + 1, month=1)
        return value.replace(month=value.month + 1)
    if bin_size == "year":
        return value.replace(year=value.year + 1)
    raise ValueError(f"unsupported bin_size: {bin_size!r}")


def _interval_type(row: JsonObject) -> IntervalType | None:
    interval_type = row.get("interval_type")
    if interval_type in INTERVAL_TYPES:
        return interval_type
    return None


def _required_text(value: object, field_name: str) -> str:
    if value is None or str(value).strip() == "":
        raise ValueError(f"{field_name} is required")
    return str(value)


def _instrument_serial_from_row(row: JsonObject) -> str | None:
    provenance = row.get("provenance")
    if not isinstance(provenance, dict):
        return None
    records_file = provenance.get("records_file")
    if records_file is None:
        return None
    parts = _record_filename_parts(str(records_file))
    if parts is None:
        return None
    return parts[1]


def _record_filename_parts(filename: str) -> tuple[str, str | None] | None:
    if not filename.endswith(".jsonl"):
        return None
    stem = filename[: -len(".jsonl")]
    if not stem:
        return None
    if "." not in stem:
        return stem, None
    family, instrument_serial = stem.split(".", 1)
    if not family or not instrument_serial:
        return None
    return family, instrument_serial


def _sort_key(item: tuple[_BinKey, _BinTotals]) -> tuple[str, str, int, datetime]:
    instrument_id, instrument_serial, bin_size, bin_start = item[0]
    return (
        instrument_id,
        instrument_serial or "",
        BIN_SIZES.index(bin_size),
        bin_start,
    )
