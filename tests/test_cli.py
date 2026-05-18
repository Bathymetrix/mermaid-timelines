from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from mermaid_timeline.cli import main
from mermaid_timeline.plotting import MissingPlotlyError


class CliTests(unittest.TestCase):
    def test_cli_build_writes_interval_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_dir = tmp_path / "records" / "467.174-T-0100"
            input_dir.mkdir(parents=True)
            _write_jsonl(
                input_dir / "log_acquisition_records.jsonl",
                [
                    {
                        "instrument_id": "0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2023-11-20T10:00:00",
                        "acquisition_state": "started",
                        "acquisition_evidence_kind": "transition",
                    },
                    {
                        "instrument_id": "0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2023-11-20T11:00:00",
                        "acquisition_state": "stopped",
                        "acquisition_evidence_kind": "transition",
                    },
                ],
            )
            _write_jsonl(
                input_dir / "mer_event_records.jsonl",
                [
                    {
                        "instrument_id": "0100",
                        "source_file": "0100_event.MER",
                        "date": "2024-02-07T22:47:22",
                        "criterion": None,
                        "snr": None,
                        "trig": None,
                        "detrig": None,
                        "sampling_rate": "20.000000",
                        "length": "2",
                    }
                ],
            )

            output_root = tmp_path / "timeline"
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "build",
                        "--input-root",
                        str(tmp_path / "records"),
                        "--output-root",
                        str(output_root),
                    ]
                )

            self.assertEqual(exit_code, 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(
                summary,
                {
                    "buffer_intervals": 1,
                    "detreq_intervals": 1,
                    "diagnostics": 0,
                    "directories": 1,
                },
            )
            output_dir = output_root / "467.174-T-0100"
            self.assertEqual(
                _read_jsonl(output_dir / "buffer_intervals.jsonl")[0][
                    "interval_type"
                ],
                "buf",
            )
            self.assertEqual(
                _read_jsonl(output_dir / "detreq_intervals.jsonl")[0][
                    "interval_type"
                ],
                "req",
            )

    def test_cli_diagnostic_mode_writes_diagnostics_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_dir = tmp_path / "records" / "467.174-T-0100"
            input_dir.mkdir(parents=True)
            _write_jsonl(
                input_dir / "log_acquisition_records.jsonl",
                [
                    {
                        "instrument_id": "0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2023-11-20T10:00:00",
                        "acquisition_state": "stopped",
                        "acquisition_evidence_kind": "transition",
                    }
                ],
            )

            output_root = tmp_path / "timeline"
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "build",
                        "--input-root",
                        str(tmp_path / "records"),
                        "--output-root",
                        str(output_root),
                        "--validation",
                        "diagnostic",
                    ]
                )

            self.assertEqual(exit_code, 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["diagnostics"], 1)

            diagnostics = _read_jsonl(
                output_root / "467.174-T-0100" / "timeline_diagnostics.jsonl"
            )
            self.assertEqual(
                diagnostics,
                [
                    {
                        "severity": "warning",
                        "code": "orphan_stop_transition",
                        "message": (
                            "stopped transition encountered with no active interval"
                        ),
                        "records_file": "log_acquisition_records.jsonl",
                        "record_line": 1,
                        "instrument_id": "0100",
                        "source_file": "0100_acq.LOG",
                    }
                ],
            )

    def test_cli_plot_help_succeeds(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as cm:
                main(["plot", "--help"])

        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--input-root", output.getvalue())
        self.assertIn("--instrument-id", output.getvalue())

    def test_cli_plot_writes_html_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            output_dir = tmp_path / "timeline" / "467.174-T-0100"
            _write_jsonl(
                output_dir / "buffer_intervals.jsonl",
                [
                    {
                        "instrument_id": "0100",
                        "interval_type": "buf",
                        "start_time": "2023-11-20T10:00:00Z",
                        "end_time": None,
                        "start_boundary": "closed",
                        "end_boundary": "open_unknown",
                        "provenance": {
                            "records_file": "log_acquisition_records.jsonl",
                            "start_record_line": 1,
                            "end_record_line": None,
                            "source_file": "0100_acq.LOG",
                        },
                    }
                ],
            )
            _write_jsonl(
                output_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "0100",
                        "interval_type": "det",
                        "start_time": "2024-02-07T22:47:22Z",
                        "end_time": "2024-02-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                        "provenance": {
                            "records_file": "mer_event_records.jsonl",
                            "record_line": 4,
                            "source_file": "0100_event.MER",
                        },
                    },
                    {
                        "instrument_id": "0200",
                        "interval_type": "req",
                        "start_time": "2024-02-07T22:48:22Z",
                        "end_time": "2024-02-07T22:48:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                        "provenance": {
                            "records_file": "mer_event_records.jsonl",
                            "record_line": 5,
                            "source_file": "0200_event.MER",
                        },
                    },
                ],
            )

            report_path = tmp_path / "timeline.html"
            output = io.StringIO()
            with patch(
                "mermaid_timeline.plotting._load_plotly",
                return_value=(_FakeGo, _fake_plot),
            ), redirect_stdout(output):
                exit_code = main(
                    [
                        "plot",
                        "--input-root",
                        str(tmp_path / "timeline"),
                        "--output",
                        str(report_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue())["intervals"], 3)
            html = report_path.read_text(encoding="utf-8")
            self.assertIn("0100", html)
            self.assertIn("0200", html)
            self.assertIn("buf", html)
            self.assertIn("det", html)
            self.assertIn("req", html)
            self.assertIn("open-ended; true end unknown", html)

    def test_cli_plot_instrument_filter_reduces_html_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            output_dir = tmp_path / "timeline" / "467.174-T-0100"
            _write_jsonl(
                output_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "0100",
                        "interval_type": "det",
                        "start_time": "2024-02-07T22:47:22Z",
                        "end_time": "2024-02-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    },
                    {
                        "instrument_id": "0200",
                        "interval_type": "req",
                        "start_time": "2024-02-07T22:48:22Z",
                        "end_time": "2024-02-07T22:48:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    },
                ],
            )

            report_path = tmp_path / "timeline.html"
            output = io.StringIO()
            with patch(
                "mermaid_timeline.plotting._load_plotly",
                return_value=(_FakeGo, _fake_plot),
            ), redirect_stdout(output):
                exit_code = main(
                    [
                        "plot",
                        "--input-root",
                        str(tmp_path / "timeline"),
                        "--output",
                        str(report_path),
                        "--instrument-id",
                        "0100",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue())["intervals"], 1)
            html = report_path.read_text(encoding="utf-8")
            self.assertIn("0100", html)
            self.assertNotIn("0200", html)

    def test_cli_plot_time_filters_reduce_html_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            output_dir = tmp_path / "timeline" / "467.174-T-0100"
            _write_jsonl(
                output_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "0100",
                        "interval_type": "det",
                        "start_time": "2024-02-07T22:47:22Z",
                        "end_time": "2024-02-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    },
                    {
                        "instrument_id": "0100",
                        "interval_type": "req",
                        "start_time": "2024-03-07T22:48:22Z",
                        "end_time": "2024-03-07T22:48:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    },
                ],
            )

            report_path = tmp_path / "timeline.html"
            output = io.StringIO()
            with patch(
                "mermaid_timeline.plotting._load_plotly",
                return_value=(_FakeGo, _fake_plot),
            ), redirect_stdout(output):
                exit_code = main(
                    [
                        "plot",
                        "--input-root",
                        str(tmp_path / "timeline"),
                        "--output",
                        str(report_path),
                        "--start-time",
                        "2024-03-01T00:00:00Z",
                        "--end-time",
                        "2024-03-31T00:00:00Z",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue())["intervals"], 1)
            html = report_path.read_text(encoding="utf-8")
            self.assertIn("req", html)
            self.assertNotIn("det", html)

    def test_cli_plot_reports_missing_plotly_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            report_path = tmp_path / "timeline.html"
            stderr = io.StringIO()
            with patch(
                "mermaid_timeline.plotting._load_plotly",
                side_effect=MissingPlotlyError(
                    "Plotly is required for 'mermaid-timeline plot'. "
                    "Install with: pip install 'mermaid-timeline[plot]'"
                ),
            ), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "plot",
                        "--input-root",
                        str(tmp_path),
                        "--output",
                        str(report_path),
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertIn("mermaid-timeline[plot]", stderr.getvalue())


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class _FakeTrace:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class _FakeFigure:
    def __init__(self) -> None:
        self.data: list[_FakeTrace] = []

    def add_trace(self, trace: _FakeTrace) -> None:
        self.data.append(trace)

    def update_layout(self, **_: object) -> None:
        return None

    def update_yaxes(self, **_: object) -> None:
        return None


class _FakeGo:
    Figure = _FakeFigure
    Scatter = _FakeTrace


def _fake_plot(
    figure: _FakeFigure,
    *,
    include_plotlyjs: bool,
    output_type: str,
    auto_open: bool,
) -> str:
    del include_plotlyjs, output_type, auto_open
    chunks: list[str] = []
    for trace in figure.data:
        chunks.append(str(trace.name))
        chunks.extend(str(item) for item in trace.y)
        chunks.extend(str(item) for item in trace.text)
    return "\n".join(chunks)


if __name__ == "__main__":
    unittest.main()
