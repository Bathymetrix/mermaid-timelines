"""Filesystem pipeline for normalized records roots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mermaid_timeline.buffer import (
    ACQUISITION_RECORDS_FILE,
    build_buffer_intervals_from_records,
)
from mermaid_timeline.detreq import MER_EVENT_RECORDS_FILE, build_detreq_intervals_from_records
from mermaid_timeline.diagnostics import Diagnostic, ValidationMode
from mermaid_timeline.records import iter_jsonl, write_jsonl

BUFFER_INTERVALS_FILE = "buffer_intervals.jsonl"
DETREQ_INTERVALS_FILE = "detreq_intervals.jsonl"
DIAGNOSTICS_FILE = "timeline_diagnostics.jsonl"


@dataclass(frozen=True, slots=True)
class TimelineDirectorySummary:
    input_dir: Path
    output_dir: Path
    buffer_intervals: int
    detreq_intervals: int
    diagnostics: int


@dataclass(frozen=True, slots=True)
class TimelinePipelineSummary:
    directories: list[TimelineDirectorySummary]

    @property
    def buffer_intervals(self) -> int:
        return sum(summary.buffer_intervals for summary in self.directories)

    @property
    def detreq_intervals(self) -> int:
        return sum(summary.detreq_intervals for summary in self.directories)

    @property
    def diagnostics(self) -> int:
        return sum(summary.diagnostics for summary in self.directories)


def run_timeline_pipeline(
    input_root: Path,
    output_root: Path,
    *,
    validation: ValidationMode = "strict",
) -> TimelinePipelineSummary:
    """Synthesize timeline products for every normalized records directory."""

    input_root = input_root.resolve()
    output_root = output_root.resolve()
    summaries: list[TimelineDirectorySummary] = []

    for input_dir in _discover_record_dirs(input_root):
        relative_dir = input_dir.relative_to(input_root)
        output_dir = output_root / relative_dir
        summaries.append(
            synthesize_directory(input_dir, output_dir, validation=validation)
        )

    return TimelinePipelineSummary(directories=summaries)


def synthesize_directory(
    input_dir: Path,
    output_dir: Path,
    *,
    validation: ValidationMode = "strict",
) -> TimelineDirectorySummary:
    diagnostics: list[Diagnostic] = []
    buffer_count = 0
    detreq_count = 0

    acquisition_path = input_dir / ACQUISITION_RECORDS_FILE
    if acquisition_path.exists():
        result = build_buffer_intervals_from_records(
            list(iter_jsonl(acquisition_path)),
            records_file=ACQUISITION_RECORDS_FILE,
            validation=validation,
        )
        buffer_count = write_jsonl(output_dir / BUFFER_INTERVALS_FILE, result.intervals)
        diagnostics.extend(result.diagnostics)

    event_path = input_dir / MER_EVENT_RECORDS_FILE
    if event_path.exists():
        result = build_detreq_intervals_from_records(
            list(iter_jsonl(event_path)),
            records_file=MER_EVENT_RECORDS_FILE,
            validation=validation,
        )
        detreq_count = write_jsonl(output_dir / DETREQ_INTERVALS_FILE, result.intervals)
        diagnostics.extend(result.diagnostics)

    if diagnostics:
        write_jsonl(
            output_dir / DIAGNOSTICS_FILE,
            [diagnostic.to_json() for diagnostic in diagnostics],
        )

    return TimelineDirectorySummary(
        input_dir=input_dir,
        output_dir=output_dir,
        buffer_intervals=buffer_count,
        detreq_intervals=detreq_count,
        diagnostics=len(diagnostics),
    )


def _discover_record_dirs(input_root: Path) -> list[Path]:
    names = {ACQUISITION_RECORDS_FILE, MER_EVENT_RECORDS_FILE}
    return sorted({path.parent for name in names for path in input_root.rglob(name)})
