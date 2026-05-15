"""Command-line interface for mermaid-timeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from mermaid_timeline.diagnostics import TimelineValidationError
from mermaid_timeline.pipeline import run_timeline_pipeline


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

    parser.print_help(sys.stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mermaid-timeline",
        description="Synthesize interval timeline products from normalized MERMAID records.",
    )
    subparsers = parser.add_subparsers(dest="command")

    build = subparsers.add_parser(
        "build",
        help="build buffer_intervals.jsonl and detreq_intervals.jsonl",
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

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
