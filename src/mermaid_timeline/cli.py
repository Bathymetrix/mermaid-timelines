"""Command-line interface for mermaid-timeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from mermaid_timeline.diagnostics import TimelineValidationError
from mermaid_timeline.pipeline import run_timeline_pipeline
from mermaid_timeline.plotting import (
    MissingPlotlyError,
    _ensure_html_suffix,
    _write_instrument_availability_html,
    parse_plot_filters,
    write_availability_html,
)


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
        input_root = Path(args.input)
        output_root = Path(args.output) if args.output is not None else input_root
        try:
            summary = run_timeline_pipeline(
                input_root,
                output_root,
                validation=args.validation,
            )
        except TimelineValidationError as exc:
            print(f"mermaid-timeline: validation failed: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"mermaid-timeline: build failed: {exc}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "directories": len(summary.directories),
                    "buffer_intervals": summary.buffer_intervals,
                    "detreq_intervals": summary.detreq_intervals,
                    "diagnostics": summary.diagnostics,
                },
                sort_keys=True,
            )
        )
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mermaid-timeline",
        description="Synthesize interval timeline products from normalized MERMAID records.",
        formatter_class=_CompactOptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    build = subparsers.add_parser(
        "build",
        help="build buffer_intervals.jsonl and detreq_intervals.jsonl",
        formatter_class=_CompactOptionHelpFormatter,
    )
    build.add_argument(
        "-i",
        "--input",
        required=True,
        help="normalized mermaid-records output directory",
    )
    build.add_argument(
        "-o",
        "--output",
        help="directory where timeline JSONL outputs will be written (default: input)",
    )
    build.add_argument(
        "--validation",
        choices=("strict", "diagnostic"),
        default="strict",
        help="validation mode (default: strict)",
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
        "--instrument-id",
        help="5-character station name to include, such as T0100",
    )
    instrument_selector.add_argument(
        "--instrument-serial",
        help="full instrument serial subdirectory to include, such as 467.174-T-0100",
    )
    plot.add_argument(
        "--start-time",
        help="include intervals overlapping this ISO-8601 lower bound",
    )
    plot.add_argument(
        "--end-time",
        help="include intervals overlapping this ISO-8601 upper bound",
    )

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
