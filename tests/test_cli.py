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
                        "--input",
                        str(tmp_path / "records"),
                        "--output",
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

    def test_cli_build_defaults_output_to_input_directory(self) -> None:
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
                    }
                ],
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["build", "--input", str(tmp_path / "records")])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue())["buffer_intervals"], 1)
            self.assertTrue((input_dir / "buffer_intervals.jsonl").exists())

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
                        "--input",
                        str(tmp_path / "records"),
                        "--output",
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
                        "input_file": str(
                            (input_dir / "log_acquisition_records.jsonl").resolve()
                        ),
                        "record_line": 1,
                        "issue_time": "2023-11-20T10:00:00Z",
                        "instrument_id": "0100",
                        "source_file": "0100_acq.LOG",
                    }
                ],
            )

    def test_cli_build_help_collapses_duplicate_metavars(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as cm:
                main(["build", "--help"])

        self.assertEqual(cm.exception.code, 0)
        self.assertIn("-i, --input INPUT", output.getvalue())
        self.assertIn("-o, --output OUTPUT", output.getvalue())
        self.assertNotIn("-i INPUT, --input INPUT", output.getvalue())

    def test_cli_plot_help_succeeds(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as cm:
                main(["plot", "--help"])

        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--input", output.getvalue())
        self.assertIn("--combined", output.getvalue())
        self.assertIn("--instrument-id", output.getvalue())
        self.assertIn("--instrument-serial", output.getvalue())
        self.assertIn("-i, --input INPUT", output.getvalue())
        self.assertNotIn("-i INPUT, --input INPUT", output.getvalue())

    def test_cli_plot_combined_writes_merged_html_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            output_dir = tmp_path / "timeline" / "467.174-T-0100"
            _write_jsonl(
                output_dir / "buffer_intervals.jsonl",
                [
                    {
                        "instrument_id": "T0100",
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
                        "instrument_id": "T0100",
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
                        "instrument_id": "T0200",
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

            report_base = tmp_path / "timeline-report"
            report_path = report_base.with_suffix(".html")
            output = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "mermaid_timeline.plotting._load_plotly",
                return_value=(_FakeGo, _fake_plot),
            ), redirect_stdout(output), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "plot",
                        "--input",
                        str(tmp_path / "timeline"),
                        "--combined",
                        "--output",
                        str(report_base),
                    ]
                )

            self.assertEqual(exit_code, 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["intervals"], 3)
            self.assertEqual(summary["output"], str(report_path))
            self.assertIn("mermaid-timeline: plotting", stderr.getvalue())
            self.assertIn(str(report_path), stderr.getvalue())
            html = report_path.read_text(encoding="utf-8")
            self.assertIn("T0100", html)
            self.assertIn("T0200", html)
            self.assertIn("buf", html)
            self.assertIn("det", html)
            self.assertIn("req", html)
            self.assertIn("float_serial: 467.174", html)
            self.assertIn("timeline_subdir: 467.174-T-0100", html)
            self.assertIn("open-ended; true end unknown", html)

    def test_cli_plot_defaults_to_one_html_report_per_instrument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            first_dir = tmp_path / "timeline" / "452.120-R-0065"
            second_dir = tmp_path / "timeline" / "467.174-T-0100"
            nested_dir = tmp_path / "timeline" / "nested" / "999.999-T-9999"
            _write_jsonl(
                first_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "R0065",
                        "interval_type": "det",
                        "start_time": "2024-02-07T22:47:22Z",
                        "end_time": "2024-02-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    }
                ],
            )
            _write_jsonl(
                nested_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "T9999",
                        "interval_type": "req",
                        "start_time": "2024-04-07T22:47:22Z",
                        "end_time": "2024-04-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    }
                ],
            )
            _write_jsonl(
                second_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "interval_type": "req",
                        "start_time": "2024-03-07T22:47:22Z",
                        "end_time": "2024-03-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    }
                ],
            )

            output = io.StringIO()
            stderr = io.StringIO()
            with patch(
                "mermaid_timeline.plotting._load_plotly",
                return_value=(_FakeGo, _fake_plot),
            ), redirect_stdout(output), redirect_stderr(stderr):
                exit_code = main(["plot", "--input", str(tmp_path / "timeline")])

            first_report = first_dir / "R0065_data_intervals.html"
            second_report = second_dir / "T0100_data_intervals.html"
            nested_report = nested_dir / "T9999_data_intervals.html"
            summary = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["intervals"], 2)
            self.assertEqual(summary["reports"], 2)
            self.assertEqual(
                {Path(item["output"]).resolve() for item in summary["outputs"]},
                {first_report.resolve(), second_report.resolve()},
            )
            self.assertFalse(nested_report.exists())
            self.assertIn("input directories", stderr.getvalue())
            first_html = first_report.read_text(encoding="utf-8")
            second_html = second_report.read_text(encoding="utf-8")
            self.assertIn("R0065", first_html)
            self.assertNotIn("T0100", first_html)
            self.assertIn("T0100", second_html)
            self.assertNotIn("R0065", second_html)

    def test_cli_plot_instrument_filter_reduces_html_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            first_dir = tmp_path / "timeline" / "467.174-T-0100"
            second_dir = tmp_path / "timeline" / "467.175-T-0200"
            _write_jsonl(
                first_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "interval_type": "det",
                        "start_time": "2024-02-07T22:47:22Z",
                        "end_time": "2024-02-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    },
                ],
            )
            _write_jsonl(
                second_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "T0200",
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
                        "--input",
                        str(tmp_path / "timeline"),
                        "--output",
                        str(report_path),
                        "--instrument-id",
                        "T0100",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue())["intervals"], 1)
            html = report_path.read_text(encoding="utf-8")
            self.assertIn("T0100", html)
            self.assertNotIn("T0200", html)

    def test_cli_plot_instrument_serial_selects_exact_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            first_dir = tmp_path / "timeline" / "467.174-T-0100"
            second_dir = tmp_path / "timeline" / "467.175-T-0200"
            _write_jsonl(
                first_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "interval_type": "det",
                        "start_time": "2024-02-07T22:47:22Z",
                        "end_time": "2024-02-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    },
                ],
            )
            _write_jsonl(
                second_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "T0200",
                        "interval_type": "req",
                        "start_time": "2024-02-07T22:48:22Z",
                        "end_time": "2024-02-07T22:48:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    },
                ],
            )

            report_base = tmp_path / "selected-report"
            report_path = report_base.with_suffix(".html")
            output = io.StringIO()
            with patch(
                "mermaid_timeline.plotting._load_plotly",
                return_value=(_FakeGo, _fake_plot),
            ), redirect_stdout(output):
                exit_code = main(
                    [
                        "plot",
                        "--input",
                        str(tmp_path / "timeline"),
                        "--output",
                        str(report_base),
                        "--instrument-serial",
                        "467.174-T-0100",
                    ]
                )

            self.assertEqual(exit_code, 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["intervals"], 1)
            self.assertEqual(summary["outputs"][0]["instrument_id"], "T0100")
            self.assertEqual(summary["outputs"][0]["output"], str(report_path))
            html = report_path.read_text(encoding="utf-8")
            self.assertIn("T0100", html)
            self.assertNotIn("T0200", html)

    def test_cli_plot_instrument_id_requires_five_character_station(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "plot",
                        "--input",
                        tmp_name,
                        "--instrument-id",
                        "0100",
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertIn("5-character station name", stderr.getvalue())

    def test_cli_plot_instrument_id_reports_multiple_serial_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            (tmp_path / "timeline" / "467.174-T-0100").mkdir(parents=True)
            (tmp_path / "timeline" / "999.999-T-0100").mkdir(parents=True)

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "plot",
                        "--input",
                        str(tmp_path / "timeline"),
                        "--instrument-id",
                        "T0100",
                    ]
                )

            self.assertEqual(exit_code, 1)
            error = stderr.getvalue()
            self.assertIn("matched multiple serial subdirectories", error)
            self.assertIn("467.174-T-0100", error)
            self.assertIn("999.999-T-0100", error)

    def test_cli_plot_time_filters_reduce_html_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            output_dir = tmp_path / "timeline" / "467.174-T-0100"
            _write_jsonl(
                output_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "interval_type": "det",
                        "start_time": "2024-02-07T22:47:22Z",
                        "end_time": "2024-02-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    },
                    {
                        "instrument_id": "T0100",
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
                        "--input",
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
            intervals_dir = tmp_path / "467.174-T-0100"
            intervals_dir.mkdir()
            (intervals_dir / "detreq_intervals.jsonl").write_text("", encoding="utf-8")
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
                        "--input",
                        str(tmp_path),
                        "--output",
                        str(report_path),
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertIn("mermaid-timeline[plot]", stderr.getvalue())

    def test_cli_build_reports_jsonl_parse_file_line_and_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_dir = tmp_path / "records" / "467.174-T-0100"
            input_dir.mkdir(parents=True)
            records_path = input_dir / "log_acquisition_records.jsonl"
            records_path.write_text(
                '{"instrument_id":"0100"}\n{"instrument_id":\n',
                encoding="utf-8",
            )

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "build",
                        "--input",
                        str(tmp_path / "records"),
                        "--output",
                        str(tmp_path / "timeline"),
                    ]
                )

            error = stderr.getvalue()
            self.assertEqual(exit_code, 1)
            self.assertIn(f"file: {records_path.resolve()}", error)
            self.assertIn("line: 2", error)
            self.assertIn("column:", error)

    def test_cli_build_reports_validation_file_line_field_and_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_dir = tmp_path / "records" / "467.174-T-0100"
            input_dir.mkdir(parents=True)
            records_path = input_dir / "mer_event_records.jsonl"
            _write_jsonl(
                records_path,
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
                    },
                    {
                        "instrument_id": "0100",
                        "source_file": "0100_event.MER",
                        "date": "2024-02-07T22:48:22",
                        "criterion": None,
                        "snr": None,
                        "trig": None,
                        "detrig": None,
                        "sampling_rate": None,
                        "length": "2",
                    },
                ],
            )

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "build",
                        "--input",
                        str(tmp_path / "records"),
                        "--output",
                        str(tmp_path / "timeline"),
                    ]
                )

            error = stderr.getvalue()
            self.assertEqual(exit_code, 1)
            self.assertIn("Invalid DET/REQ interval record", error)
            self.assertIn(f"file: {records_path.resolve()}", error)
            self.assertIn("line: 2", error)
            self.assertIn("field: sampling_rate", error)
            self.assertIn("value: null", error)
            self.assertIn("expected: positive number", error)

    def test_cli_plot_reports_interval_file_line_and_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            output_dir = tmp_path / "timeline" / "467.174-T-0100"
            intervals_path = output_dir / "detreq_intervals.jsonl"
            _write_jsonl(
                intervals_path,
                [
                    {
                        "instrument_id": "0100",
                        "interval_type": "det",
                        "end_time": "2024-02-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    },
                ],
            )

            stderr = io.StringIO()
            with patch(
                "mermaid_timeline.plotting._load_plotly",
                return_value=(_FakeGo, _fake_plot),
            ), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "plot",
                        "--input",
                        str(tmp_path / "timeline"),
                        "--output",
                        str(tmp_path / "timeline.html"),
                    ]
                )

            error = stderr.getvalue()
            self.assertEqual(exit_code, 1)
            self.assertIn(f"file: {intervals_path.resolve()}", error)
            self.assertIn("line: 1", error)
            self.assertIn("field: start_time", error)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"{path}:{line_number}:{exc.colno}: invalid JSONL in test fixture"
            ) from exc
    return rows


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
