"""Timestamp parsing and formatting helpers."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_timestamp(value: object, *, field_name: str) -> datetime:
    """Parse a normalized timestamp and return a UTC-aware datetime."""

    if value is None:
        raise ValueError(f"{field_name} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} is not an ISO timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime | None) -> str | None:
    """Format a datetime as an ISO-8601 UTC string with a trailing Z."""

    if value is None:
        return None
    utc_value = value.astimezone(timezone.utc)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
