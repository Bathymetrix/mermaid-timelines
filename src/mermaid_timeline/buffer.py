"""Synthesize BUF intervals from normalized acquisition records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import groupby

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

ACQUISITION_RECORDS_FILE = "log_acquisition_records.jsonl"


@dataclass(frozen=True, slots=True)
class TimelineResult:
    intervals: list[JsonObject]
    diagnostics: list[Diagnostic]


@dataclass(frozen=True, slots=True)
class _AcquisitionEvent:
    line_number: int
    row: JsonObject
    instrument_id: str
    state: str
    evidence_kind: str
    time: datetime
    sort_time: datetime


@dataclass(slots=True)
class _OpenInterval:
    record: _AcquisitionEvent


def build_buffer_intervals(
    rows: JsonRows,
    *,
    records_file: str = ACQUISITION_RECORDS_FILE,
    validation: ValidationMode = "strict",
) -> TimelineResult:
    """Build BUF intervals from normalized acquisition JSONL rows."""

    return build_buffer_intervals_from_records(
        source_records(rows), records_file=records_file, validation=validation
    )


def build_buffer_intervals_from_records(
    records: SourceRecords,
    *,
    records_file: str = ACQUISITION_RECORDS_FILE,
    validation: ValidationMode = "strict",
) -> TimelineResult:
    ctx = ValidationContext(validation)
    events = _validated_events(records, ctx, records_file=records_file)
    intervals: list[JsonObject] = []

    events.sort(key=lambda event: (event.instrument_id, event.sort_time, event.line_number))
    for instrument_id, grouped_events in groupby(events, key=lambda event: event.instrument_id):
        intervals.extend(
            _build_instrument_intervals(
                instrument_id,
                list(grouped_events),
                ctx,
                records_file=records_file,
            )
        )

    return TimelineResult(intervals=intervals, diagnostics=ctx.diagnostics)


def _validated_events(
    records: SourceRecords,
    ctx: ValidationContext,
    *,
    records_file: str,
) -> list[_AcquisitionEvent]:
    events: list[_AcquisitionEvent] = []
    for record in records:
        row = record.row
        instrument_id = _required_string(
            row, "instrument_id", record.line_number, ctx, records_file
        )
        state = _required_string(
            row, "acquisition_state", record.line_number, ctx, records_file
        )
        evidence_kind = _required_string(
            row,
            "acquisition_evidence_kind",
            record.line_number,
            ctx,
            records_file,
        )
        if instrument_id is None or state is None or evidence_kind is None:
            continue
        if state not in ("started", "stopped"):
            ctx.report(
                severity="error",
                code="invalid_acquisition_state",
                message=f"expected acquisition_state started/stopped, got {state!r}",
                records_file=records_file,
                record_line=record.line_number,
                row=row,
            )
            continue
        if evidence_kind not in ("transition", "assertion"):
            ctx.report(
                severity="error",
                code="invalid_acquisition_evidence_kind",
                message=(
                    "expected acquisition_evidence_kind transition/assertion, "
                    f"got {evidence_kind!r}"
                ),
                records_file=records_file,
                record_line=record.line_number,
                row=row,
            )
            continue
        try:
            parsed_time = parse_timestamp(row.get("record_time"), field_name="record_time")
        except ValueError as exc:
            ctx.report(
                severity="error",
                code="invalid_record_time",
                message=str(exc),
                records_file=records_file,
                record_line=record.line_number,
                row=row,
            )
            continue
        events.append(
            _AcquisitionEvent(
                line_number=record.line_number,
                row=row,
                instrument_id=instrument_id,
                state=state,
                evidence_kind=evidence_kind,
                time=parsed_time,
                sort_time=parsed_time,
            )
        )
    return events


def _build_instrument_intervals(
    instrument_id: str,
    events: list[_AcquisitionEvent],
    ctx: ValidationContext,
    *,
    records_file: str,
) -> list[JsonObject]:
    intervals: list[JsonObject] = []
    current: _OpenInterval | None = None

    for event in events:
        if event.state == "started" and event.evidence_kind == "transition":
            if current is not None:
                ctx.report(
                    severity="warning",
                    code="duplicate_start_transition",
                    message="started transition encountered while an interval is active",
                    records_file=records_file,
                    record_line=event.line_number,
                    row=event.row,
                )
                continue
            current = _OpenInterval(record=event)
            continue

        if event.state == "started" and event.evidence_kind == "assertion":
            if current is None:
                current = _OpenInterval(record=event)
            continue

        if event.state == "stopped" and event.evidence_kind == "transition":
            if current is None:
                ctx.report(
                    severity="warning",
                    code="orphan_stop_transition",
                    message="stopped transition encountered with no active interval",
                    records_file=records_file,
                    record_line=event.line_number,
                    row=event.row,
                )
                continue
            intervals.append(
                _interval_record(
                    instrument_id=instrument_id,
                    start=current.record,
                    end=event,
                    end_time=event.time,
                    end_boundary="closed",
                    records_file=records_file,
                )
            )
            current = None
            continue

        if event.state == "stopped" and event.evidence_kind == "assertion":
            if current is not None:
                intervals.append(
                    _interval_record(
                        instrument_id=instrument_id,
                        start=current.record,
                        end=event,
                        end_time=None,
                        end_boundary="open_unknown",
                        records_file=records_file,
                    )
                )
                current = None
            continue

    if current is not None:
        intervals.append(
            _interval_record(
                instrument_id=instrument_id,
                start=current.record,
                end=None,
                end_time=None,
                end_boundary="open_unknown",
                records_file=records_file,
            )
        )

    return intervals


def _interval_record(
    *,
    instrument_id: str,
    start: _AcquisitionEvent,
    end: _AcquisitionEvent | None,
    end_time: datetime | None,
    end_boundary: str,
    records_file: str,
) -> JsonObject:
    end_source = end.row.get("source_file") if end is not None else None
    source_file = start.row.get("source_file") or end_source
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": generated_by(),
        "instrument_id": instrument_id,
        "interval_type": "buf",
        "start_time": format_timestamp(start.time),
        "end_time": format_timestamp(end_time),
        "start_boundary": "closed",
        "end_boundary": end_boundary,
        "start_evidence_kind": start.evidence_kind,
        "end_evidence_kind": end.evidence_kind if end is not None else None,
        "start_evidence_time": format_timestamp(start.time),
        "end_evidence_time": format_timestamp(end.time) if end is not None else None,
        "provenance": {
            "records_file": records_file,
            "start_record_line": start.line_number,
            "end_record_line": end.line_number if end is not None else None,
            "source_file": source_file,
        },
    }


def _required_string(
    row: JsonObject,
    field_name: str,
    line_number: int,
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
            record_line=line_number,
            row=row,
        )
        return None
    return str(value)
