"""Validation diagnostics shared by synthesis modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, cast

from mermaid_timeline.records import JsonObject

type ValidationMode = Literal["strict", "diagnostic"]


class TimelineValidationError(ValueError):
    """Raised when strict validation encounters an invalid timeline input."""


@dataclass(slots=True)
class Diagnostic:
    severity: Literal["warning", "error"]
    code: str
    message: str
    records_file: str
    record_line: int | None = None
    issue_time: str | None = None
    instrument_id: str | None = None
    source_file: str | None = None

    def to_json(self) -> JsonObject:
        return cast(JsonObject, asdict(self))


class ValidationContext:
    """Collect diagnostics or raise immediately, depending on validation mode."""

    def __init__(self, mode: ValidationMode) -> None:
        if mode not in ("strict", "diagnostic"):
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
        record_line: int | None = None,
        row: JsonObject | None = None,
        issue_time: str | None = None,
    ) -> None:
        diagnostic = Diagnostic(
            severity=severity,
            code=code,
            message=message,
            records_file=records_file,
            record_line=record_line,
            issue_time=issue_time or _issue_time_from_row(row),
            instrument_id=_string_or_none(row.get("instrument_id")) if row else None,
            source_file=_string_or_none(row.get("source_file")) if row else None,
        )
        if self.mode == "strict":
            raise TimelineValidationError(_format_diagnostic(diagnostic))
        self.diagnostics.append(diagnostic)


def _format_diagnostic(diagnostic: Diagnostic) -> str:
    location = diagnostic.records_file
    if diagnostic.record_line is not None:
        location = f"{location}:{diagnostic.record_line}"
    return f"{diagnostic.code} at {location}: {diagnostic.message}"


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
