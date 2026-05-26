"""Synthesize DET and REQ intervals from normalized MER event records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from mermaid_timeline._time import format_timestamp, parse_timestamp
from mermaid_timeline.diagnostics import (
    Diagnostic,
    ValidationContext,
    ValidationMode,
)
from mermaid_timeline.records import (
    JsonObject,
    JsonRows,
    SourceRecord,
    SourceRecords,
    source_records,
)
from mermaid_timeline.schema import SCHEMA_VERSION, generated_by

MER_EVENT_RECORDS_FILE = "mer_event_records.jsonl"
DETECTION_FIELDS = ("criterion", "snr", "trig", "detrig")


@dataclass(frozen=True, slots=True)
class TimelineResult:
    intervals: list[JsonObject]
    diagnostics: list[Diagnostic]


def build_detreq_intervals(
    rows: JsonRows,
    *,
    records_file: str = MER_EVENT_RECORDS_FILE,
    validation: ValidationMode = "permissive",
) -> TimelineResult:
    """Build DET/REQ intervals from normalized MER event rows."""

    return build_detreq_intervals_from_records(
        source_records(rows), records_file=records_file, validation=validation
    )


def build_detreq_intervals_from_records(
    records: SourceRecords,
    *,
    records_file: str = MER_EVENT_RECORDS_FILE,
    validation: ValidationMode = "permissive",
) -> TimelineResult:
    ctx = ValidationContext(validation)
    intervals: list[JsonObject] = []

    for record in records:
        interval = _interval_from_record(record, ctx, records_file=records_file)
        if interval is not None:
            intervals.append(interval)

    return TimelineResult(intervals=intervals, diagnostics=ctx.diagnostics)


def _interval_from_record(
    record: SourceRecord,
    ctx: ValidationContext,
    *,
    records_file: str,
) -> JsonObject | None:
    row = record.row
    interval_type = _classify_interval_type(row, record, ctx, records_file=records_file)
    if interval_type is None:
        return None

    instrument_id = _required_string(row, "instrument_id", record, ctx, records_file)
    if instrument_id is None:
        return None

    try:
        start_time = parse_timestamp(row.get("date"), field_name="date")
    except ValueError as exc:
        ctx.report(
            severity="error",
            code="invalid_event_date",
            message=str(exc),
            records_file=records_file,
            input_file=_input_file(record, records_file),
            record_line=record.line_number,
            field="date",
            value=row.get("date"),
            expected="ISO-8601 timestamp",
            row=row,
            cause=exc,
            title="Invalid DET/REQ interval record",
        )
        return None

    sampling_rate = _parse_positive_float(
        row,
        "sampling_rate",
        record,
        ctx,
        records_file,
    )
    sample_count = _parse_positive_int(row, "length", record, ctx, records_file)
    if sampling_rate is None or sample_count is None:
        return None

    end_time = start_time + _sample_span(sample_count, sampling_rate)
    duration = round((end_time - start_time).total_seconds(), 6)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": generated_by(),
        "instrument_id": instrument_id,
        "interval_type": interval_type,
        "start_time": format_timestamp(start_time),
        "end_time": format_timestamp(end_time),
        "duration": duration,
        "start_boundary": "closed",
        "end_boundary": "closed",
        "sampling_rate_hz": sampling_rate,
        "sample_count": sample_count,
        "provenance": {
            "records_file": records_file,
            "record_line": record.line_number,
            "source_file": row.get("source_file"),
        },
    }


def _classify_interval_type(
    row: JsonObject,
    record: SourceRecord,
    ctx: ValidationContext,
    *,
    records_file: str,
) -> str | None:
    present = [_has_value(row.get(field)) for field in DETECTION_FIELDS]
    if all(present):
        return "det"
    if not any(present):
        return "req"
    fields = ", ".join(
        f"{field}={'present' if is_present else 'null'}"
        for field, is_present in zip(DETECTION_FIELDS, present, strict=True)
    )
    ctx.report(
        severity="error",
        code="mixed_detreq_fields",
        message=f"criterion/snr/trig/detrig must be all present or all null: {fields}",
        records_file=records_file,
        input_file=_input_file(record, records_file),
        record_line=record.line_number,
        field="criterion/snr/trig/detrig",
        value=fields,
        expected="all present for DET or all null for REQ",
        row=row,
        title="Invalid DET/REQ interval record",
    )
    return None


def _sample_span(sample_count: int, sampling_rate: float) -> timedelta:
    seconds = Decimal(sample_count - 1) / Decimal(str(sampling_rate))
    microseconds = int(
        (seconds * Decimal("1000000")).to_integral_value(rounding=ROUND_HALF_UP)
    )
    return timedelta(microseconds=microseconds)


def _parse_positive_float(
    row: JsonObject,
    field_name: str,
    record: SourceRecord,
    ctx: ValidationContext,
    records_file: str,
) -> float | None:
    value = row.get(field_name)
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        ctx.report(
            severity="error",
            code=f"invalid_{field_name}",
            message=f"{field_name} must be a positive number",
            records_file=records_file,
            input_file=_input_file(record, records_file),
            record_line=record.line_number,
            field=field_name,
            value=value,
            expected="positive number",
            row=row,
            cause=exc,
            title="Invalid DET/REQ interval record",
        )
        return None
    if parsed <= 0:
        ctx.report(
            severity="error",
            code=f"invalid_{field_name}",
            message=f"{field_name} must be positive",
            records_file=records_file,
            input_file=_input_file(record, records_file),
            record_line=record.line_number,
            field=field_name,
            value=value,
            expected="positive number",
            row=row,
            title="Invalid DET/REQ interval record",
        )
        return None
    return parsed


def _parse_positive_int(
    row: JsonObject,
    field_name: str,
    record: SourceRecord,
    ctx: ValidationContext,
    records_file: str,
) -> int | None:
    value = row.get(field_name)
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        ctx.report(
            severity="error",
            code=f"invalid_{field_name}",
            message=f"{field_name} must be a positive integer",
            records_file=records_file,
            input_file=_input_file(record, records_file),
            record_line=record.line_number,
            field=field_name,
            value=value,
            expected="positive integer",
            row=row,
            cause=exc,
            title="Invalid DET/REQ interval record",
        )
        return None
    if parsed <= 0:
        ctx.report(
            severity="error",
            code=f"invalid_{field_name}",
            message=f"{field_name} must be positive",
            records_file=records_file,
            input_file=_input_file(record, records_file),
            record_line=record.line_number,
            field=field_name,
            value=value,
            expected="positive integer",
            row=row,
            title="Invalid DET/REQ interval record",
        )
        return None
    return parsed


def _required_string(
    row: JsonObject,
    field_name: str,
    record: SourceRecord,
    ctx: ValidationContext,
    records_file: str,
) -> str | None:
    value = row.get(field_name)
    if value is None or str(value).strip() == "":
        ctx.report(
            severity="error",
            code="missing_field",
            message=f"{field_name} is required",
            records_file=records_file,
            input_file=_input_file(record, records_file),
            record_line=record.line_number,
            field=field_name,
            value=value,
            expected="non-empty string",
            row=row,
            title="Invalid DET/REQ interval record",
        )
        return None
    return str(value)


def _has_value(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def _input_file(record: SourceRecord, records_file: str) -> str:
    return str(record.source_path) if record.source_path is not None else records_file
