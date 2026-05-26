"""Validation diagnostics shared by synthesis modules."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from mermaid_timeline.records import JsonObject, display_path

type ValidationMode = Literal["strict", "permissive", "diagnostic"]
_MISSING = object()


class TimelineValidationError(ValueError):
    """Raised when strict validation encounters an invalid timeline input."""


@dataclass(slots=True)
class Diagnostic:
    severity: Literal["warning", "error"]
    code: str
    message: str
    records_file: str
    input_file: str | None = None
    record_line: int | None = None
    field: str | None = None
    value: str | None = None
    expected: str | None = None
    issue_time: str | None = None
    instrument_id: str | None = None
    source_file: str | None = None

    def to_json(self) -> JsonObject:
        data = asdict(self)
        for key in ("input_file", "field", "value", "expected"):
            if data[key] is None:
                del data[key]
        return cast(JsonObject, data)


class ValidationContext:
    """Collect diagnostics or raise immediately, depending on validation mode."""

    def __init__(self, mode: ValidationMode) -> None:
        if mode == "diagnostic":
            mode = "permissive"
        if mode not in ("strict", "permissive"):
            raise ValueError(f"unknown validation mode: {mode!r}")
        self.mode = mode
        self.diagnostics: list[Diagnostic] = []

    def report(
        self,
        *,
        severity: Literal["warning", "error"],
        code: str,
        message: str,
        records_file: str,
        input_file: Path | str | None = None,
        record_line: int | None = None,
        field: str | None = None,
        value: object = _MISSING,
        expected: str | None = None,
        row: JsonObject | None = None,
        issue_time: str | None = None,
        cause: BaseException | None = None,
        title: str = "Invalid timeline input record",
    ) -> None:
        has_value = value is not _MISSING
        diagnostic = Diagnostic(
            severity=severity,
            code=code,
            message=message,
            records_file=records_file,
            input_file=display_path(input_file) if input_file is not None else None,
            record_line=record_line,
            field=field,
            value=_format_diagnostic_value(value) if has_value else None,
            expected=expected,
            issue_time=issue_time or _issue_time_from_row(row),
            instrument_id=_string_or_none(row.get("instrument_id")) if row else None,
            source_file=_string_or_none(row.get("source_file")) if row else None,
        )
        if self.mode == "strict":
            error = TimelineValidationError(_format_diagnostic(diagnostic, title=title))
            if cause is not None:
                raise error from cause
            raise error
        self.diagnostics.append(diagnostic)


def _format_diagnostic(
    diagnostic: Diagnostic,
    *,
    title: str,
) -> str:
    lines = [
        f"{title}:",
        f"  file: {diagnostic.input_file or diagnostic.records_file}",
    ]
    if diagnostic.record_line is not None:
        lines.append(f"  line: {diagnostic.record_line}")
    lines.append(f"  code: {diagnostic.code}")
    if diagnostic.field is not None:
        lines.append(f"  field: {diagnostic.field}")
    if diagnostic.value is not None:
        lines.append(f"  value: {diagnostic.value}")
    if diagnostic.expected is not None:
        lines.append(f"  expected: {diagnostic.expected}")
    if diagnostic.source_file is not None:
        lines.append(f"  source_file: {diagnostic.source_file}")
    if diagnostic.instrument_id is not None:
        lines.append(f"  instrument_id: {diagnostic.instrument_id}")
    lines.append(f"  message: {diagnostic.message}")
    return "\n".join(lines)


def _format_diagnostic_value(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _issue_time_from_row(row: JsonObject | None) -> str | None:
    if row is None:
        return None
    for field_name in ("record_time", "date"):
        value = _string_or_none(row.get(field_name))
        if value is not None:
            return value
    return None
