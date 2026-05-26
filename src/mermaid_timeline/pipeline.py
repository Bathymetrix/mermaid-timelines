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
from mermaid_timeline.summary import build_summary_intervals_from_files

BUFFER_INTERVALS_FILE = "buffer_intervals.jsonl"
DETREQ_INTERVALS_FILE = "detreq_intervals.jsonl"
SUMMARY_INTERVALS_FILE = "summary_intervals.jsonl"
DIAGNOSTICS_FILE = "timeline_diagnostics.jsonl"
_JSONL_SUFFIX = ".jsonl"


@dataclass(frozen=True, slots=True)
class TimelineDirectorySummary:
    input_dir: Path
    output_dir: Path
    buffer_intervals: int
    detreq_intervals: int
    summary_intervals: int
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
    def summary_intervals(self) -> int:
        return sum(summary.summary_intervals for summary in self.directories)

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
    summary_count = 0
    buffer_intervals = []
    detreq_intervals = []

    for acquisition_path in _record_files_for_family(
        input_dir, _record_family(ACQUISITION_RECORDS_FILE)
    ):
        result = build_buffer_intervals_from_records(
            list(iter_jsonl(acquisition_path)),
            records_file=acquisition_path.name,
            validation=validation,
        )
        buffer_intervals.extend(result.intervals)
        diagnostics.extend(result.diagnostics)

    if buffer_intervals:
        buffer_count = write_jsonl(output_dir / BUFFER_INTERVALS_FILE, buffer_intervals)

    for event_path in _record_files_for_family(
        input_dir, _record_family(MER_EVENT_RECORDS_FILE)
    ):
        result = build_detreq_intervals_from_records(
            list(iter_jsonl(event_path)),
            records_file=event_path.name,
            validation=validation,
        )
        detreq_intervals.extend(result.intervals)
        diagnostics.extend(result.diagnostics)

    if detreq_intervals:
        detreq_count = write_jsonl(output_dir / DETREQ_INTERVALS_FILE, detreq_intervals)

    interval_paths = [
        output_dir / filename
        for filename, count in (
            (BUFFER_INTERVALS_FILE, buffer_count),
            (DETREQ_INTERVALS_FILE, detreq_count),
        )
        if count
    ]
    if interval_paths:
        summary_intervals = build_summary_intervals_from_files(
            interval_paths,
            default_instrument_serial=input_dir.name,
        )
        if summary_intervals:
            summary_count = write_jsonl(
                output_dir / SUMMARY_INTERVALS_FILE, summary_intervals
            )

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
        summary_intervals=summary_count,
        diagnostics=len(diagnostics),
    )


def _discover_record_dirs(input_root: Path) -> list[Path]:
    families = {
        _record_family(ACQUISITION_RECORDS_FILE),
        _record_family(MER_EVENT_RECORDS_FILE),
    }
    return sorted(
        {
            path.parent
            for family in families
            for path in _record_file_candidates_for_family(input_root, family)
        }
    )


def _record_files_for_family(directory: Path, family: str) -> list[Path]:
    suffixed: list[Path] = []
    for path in directory.glob(f"{family}.*{_JSONL_SUFFIX}"):
        parts = _record_filename_parts(path.name)
        if parts is not None and parts[0] == family and parts[1] is not None:
            suffixed.append(path)
    suffixed.sort()
    if suffixed:
        return suffixed

    unsuffixed = [
        path
        for path in directory.glob(f"{family}{_JSONL_SUFFIX}")
        if _record_filename_parts(path.name) == (family, None)
    ]
    unsuffixed.sort()
    return unsuffixed


def _record_file_candidates_for_family(directory: Path, family: str) -> list[Path]:
    candidates: list[Path] = []
    for path in directory.rglob(f"{family}*{_JSONL_SUFFIX}"):
        parts = _record_filename_parts(path.name)
        if parts is not None and parts[0] == family:
            candidates.append(path)
    candidates.sort()
    return candidates


def _record_family(filename: str) -> str:
    parts = _record_filename_parts(filename)
    if parts is None:
        raise ValueError(f"not a JSONL records filename: {filename!r}")
    return parts[0]


def _record_filename_parts(filename: str) -> tuple[str, str | None] | None:
    if not filename.endswith(_JSONL_SUFFIX):
        return None
    stem = filename[: -len(_JSONL_SUFFIX)]
    if not stem:
        return None
    if "." not in stem:
        return stem, None
    family, instrument_serial = stem.split(".", 1)
    if not family or not instrument_serial:
        return None
    return family, instrument_serial
