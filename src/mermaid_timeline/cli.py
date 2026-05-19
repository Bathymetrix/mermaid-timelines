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
        try:
            summary = run_timeline_pipeline(
                Path(args.input_root),
                Path(args.output_root),
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
        input_root = Path(args.input_root)
        output = Path(args.output)
        print(
            f"mermaid-timeline: plotting {input_root} -> {output}",
            file=sys.stderr,
        )
        try:
            count = write_availability_html(
                input_root,
                output,
                filters=parse_plot_filters(
                    instrument_ids=args.instrument_id,
                    start_time=args.start_time,
                    end_time=args.end_time,
                ),
            )
        except MissingPlotlyError as exc:
            print(f"mermaid-timeline: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"mermaid-timeline: plotting failed: {exc}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {"intervals": count, "output": str(output)},
                sort_keys=True,
            )
        )
        return 0

    parser.print_help(sys.stderr)
    return 2


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
        "--input-root",
        required=True,
        help="normalized mermaid-records output root",
    )
    build.add_argument(
        "-o",
        "--output-root",
        required=True,
        help="directory where timeline JSONL outputs will be written",
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
        "--input-root",
        required=True,
        help="mermaid-timeline output root containing interval JSONL files",
    )
    plot.add_argument(
        "-o",
        "--output",
        required=True,
        help="self-contained HTML report path",
    )
    plot.add_argument(
        "--instrument-id",
        action="append",
        default=[],
        help="instrument ID to include; repeat to include multiple instruments",
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
