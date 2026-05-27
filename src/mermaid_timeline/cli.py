"""Command-line interface for mermaid-timeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from mermaid_timeline import __version__
from mermaid_timeline.diagnostics import TimelineValidationError
from mermaid_timeline.pipeline import (
    TimelineDirectorySummary,
    TimelinePipelineSummary,
    run_timeline_pipeline,
)
from mermaid_timeline.plotting import (
    MissingPlotlyError,
    _ensure_html_suffix,
    _write_instrument_availability_html,
    parse_plot_filters,
    write_availability_html,
)


MERMAID_ENV_VAR = "MERMAID"
DEFAULT_RECORDS_SUBDIR = "records"
DEFAULT_TIMELINE_SUBDIR = "timeline"
SUMMARY_REPORT_BIN_SIZE = "year"
SUMMARY_INTERVAL_TYPES = ("buf", "det", "req")


class _CompactOptionHelpFormatter(argparse.HelpFormatter):
    """Avoid repeating metavars for short and long aliases in help output."""

    def _format_action_invocation(self, action: argparse.Action) -> str:
        if not action.option_strings or action.nargs == 0:
            return super()._format_action_invocation(action)

        default = action.dest.upper()
        args_string = self._format_args(action, default)
        return ", ".join(
            [*action.option_strings[:-1], f"{action.option_strings[-1]} {args_string}"]
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        try:
            input_root = _build_input_root(args.input)
            output_root = _build_output_root(args.output)
            print("Building intervals...", file=sys.stderr)
            summary = run_timeline_pipeline(
                input_root,
                output_root,
                validation=args.validation,
                progress_callback=_print_build_directory_progress,
            )
        except TimelineValidationError as exc:
            print(f"mermaid-timeline: validation failed: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"mermaid-timeline: build failed: {exc}", file=sys.stderr)
            return 1
        _print_build_done(summary, output_root)
        return 0

    if args.command == "plot":
        input_root = Path(args.input)
        try:
            filters = parse_plot_filters(
                instrument_id=args.instrument_id,
                instrument_serial=args.instrument_serial,
                start_time=args.start_time,
                end_time=args.end_time,
            )
            if args.combined:
                output = _combined_plot_output(input_root, args.output)
                print(
                    f"mermaid-timeline: plotting combined {input_root} -> {output}",
                    file=sys.stderr,
                )
                count = write_availability_html(input_root, output, filters=filters)
                print(
                    json.dumps(
                        {"intervals": count, "output": str(output)},
                        sort_keys=True,
                    )
                )
            else:
                output = Path(args.output) if args.output is not None else None
                output_label = output if output is not None else "input directories"
                print(
                    f"mermaid-timeline: plotting per-instrument "
                    f"{input_root} -> {output_label}",
                    file=sys.stderr,
                )
                reports = _write_instrument_availability_html(
                    input_root,
                    output,
                    filters=filters,
                )
                print(
                    json.dumps(
                        {
                            "intervals": sum(
                                report.interval_count for report in reports
                            ),
                            "outputs": [
                                {
                                    "instrument_id": report.instrument_id,
                                    "intervals": report.interval_count,
                                    "output": str(report.output),
                                }
                                for report in reports
                            ],
                            "reports": len(reports),
                        },
                        sort_keys=True,
                    )
                )
        except MissingPlotlyError as exc:
            print(f"mermaid-timeline: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"mermaid-timeline: plotting failed: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.print_help(sys.stderr)
    return 2


def _combined_plot_output(input_root: Path, output: str | None) -> Path:
    if output is None:
        return input_root / "timeline.html"

    output_path = Path(output)
    if output_path.exists() and output_path.is_dir():
        return output_path / "timeline.html"
    return _ensure_html_suffix(output_path)


def _print_build_directory_progress(directory: TimelineDirectorySummary) -> None:
    for block in _build_progress_blocks(directory):
        print(f"{block['label']}:", file=sys.stderr)
        _print_interval_totals(block)


def _print_build_done(summary: TimelinePipelineSummary, output_root: Path) -> None:
    rows = [
        row
        for directory in summary.directories
        for row in directory.summary_interval_rows
        if row.get("bin_size") == SUMMARY_REPORT_BIN_SIZE
    ]
    print(f"\nDone: intervals written to {output_root}", file=sys.stderr)
    print("\nSummary:", file=sys.stderr)
    _print_interval_totals(_progress_block_from_summary_rows("Summary", rows), width=9)


def _print_interval_totals(block: dict[str, object], *, width: int = 6) -> None:
    counts = block["counts"]
    durations = block["durations"]
    for interval_type in SUMMARY_INTERVAL_TYPES:
        count = int(counts[interval_type])
        hours = float(durations[interval_type]) / 3600.0
        print(
            f"    {interval_type}: {count:>{width},} intervals [{hours:,.1f} hr]",
            file=sys.stderr,
        )


def _build_progress_blocks(
    directory: TimelineDirectorySummary,
) -> list[dict[str, object]]:
    rows_by_label: dict[str, list[dict[str, object]]] = {}
    for row in directory.summary_interval_rows:
        if row.get("bin_size") != SUMMARY_REPORT_BIN_SIZE:
            continue
        label = _summary_row_label(row, directory.input_dir)
        rows_by_label.setdefault(label, []).append(row)

    if not rows_by_label:
        return [_empty_progress_block(directory.input_dir.name)]

    return [
        _progress_block_from_summary_rows(label, rows)
        for label, rows in rows_by_label.items()
    ]


def _summary_row_label(row: dict[str, object], input_dir: Path) -> str:
    instrument_serial = row.get("instrument_serial")
    if instrument_serial is not None and str(instrument_serial).strip():
        return str(instrument_serial)
    return input_dir.name


def _empty_progress_block(label: str) -> dict[str, object]:
    return {
        "label": label,
        "counts": {interval_type: 0 for interval_type in SUMMARY_INTERVAL_TYPES},
        "durations": {interval_type: 0.0 for interval_type in SUMMARY_INTERVAL_TYPES},
    }


def _progress_block_from_summary_rows(
    label: str, rows: list[dict[str, object]]
) -> dict[str, object]:
    block = _empty_progress_block(label)
    counts = block["counts"]
    durations = block["durations"]
    for row in rows:
        row_counts = row.get("interval_count")
        row_durations = row.get("duration_seconds")
        if not isinstance(row_counts, dict) or not isinstance(row_durations, dict):
            continue
        for interval_type in SUMMARY_INTERVAL_TYPES:
            counts[interval_type] += int(row_counts.get(interval_type, 0))
            durations[interval_type] += float(row_durations.get(interval_type, 0.0))
    return block


def _build_input_root(input_arg: str | None) -> Path:
    if input_arg is not None:
        return Path(input_arg)
    return _mermaid_default_root(DEFAULT_RECORDS_SUBDIR, "--input")


def _build_output_root(output_arg: str | None) -> Path:
    if output_arg is not None:
        return Path(output_arg)
    return _mermaid_default_root(DEFAULT_TIMELINE_SUBDIR, "--output")


def _mermaid_default_root(subdir: str, option: str) -> Path:
    mermaid_root = os.environ.get(MERMAID_ENV_VAR)
    if not mermaid_root:
        raise ValueError(
            f"{option} omitted and ${MERMAID_ENV_VAR} is not set; "
            f"pass {option} or set ${MERMAID_ENV_VAR}"
        )
    return Path(mermaid_root) / subdir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mermaid-timeline",
        description="Synthesize interval timeline products from normalized MERMAID records.",
        formatter_class=_CompactOptionHelpFormatter,
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    build = subparsers.add_parser(
        "build",
        help=(
            "build buffer_intervals.jsonl, detreq_intervals.jsonl, "
            "and summary_intervals.jsonl"
        ),
        formatter_class=_CompactOptionHelpFormatter,
    )
    build.add_argument(
        "-i",
        "--input",
        help="normalized mermaid-records output directory (default: $MERMAID/records)",
    )
    build.add_argument(
        "-o",
        "--output",
        help=(
            "directory where timeline JSONL outputs will be written "
            "(default: $MERMAID/timeline)"
        ),
    )
    build.add_argument(
        "--validation",
        choices=("strict", "permissive"),
        default="permissive",
        help="validation mode (default: permissive)",
    )

    plot = subparsers.add_parser(
        "plot",
        help="write an optional Plotly HTML availability report",
        formatter_class=_CompactOptionHelpFormatter,
    )
    plot.add_argument(
        "-i",
        "--input",
        required=True,
        help=(
            "timeline output root containing instrument serial subdirectories, "
            "or one instrument serial directory"
        ),
    )
    plot.add_argument(
        "-o",
        "--output",
        help=(
            "output directory for per-instrument reports; with --combined or a "
            "single-station input/filter, self-contained HTML report path "
            "(default: input)"
        ),
    )
    plot.add_argument(
        "--combined",
        action="store_true",
        help="write one merged HTML report for all selected instruments",
    )
    instrument_selector = plot.add_mutually_exclusive_group()
    instrument_selector.add_argument(
        "--id",
        dest="instrument_id",
        help="5-character station name to include, such as T0100",
    )
    instrument_selector.add_argument(
        "--ser",
        dest="instrument_serial",
        help="full instrument serial subdirectory to include, such as 467.174-T-0100",
    )
    plot.add_argument(
        "-s",
        "--start-time",
        help="include intervals overlapping this ISO-8601 lower bound",
    )
    plot.add_argument(
        "-e",
        "--end-time",
        help="include intervals overlapping this ISO-8601 upper bound",
    )

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
