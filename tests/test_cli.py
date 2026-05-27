from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from mermaid_timeline import __version__
from mermaid_timeline.cli import main
from mermaid_timeline.interval_reader import IntervalRow
from mermaid_timeline.pipeline import TimelineDirectorySummary, TimelinePipelineSummary
from mermaid_timeline.plotting import MissingPlotlyError, _build_figure


class CliTests(unittest.TestCase):
    def test_cli_version_options_report_package_version(self) -> None:
        for option in ("--version", "-v"):
            with self.subTest(option=option):
                output = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(output), redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as cm:
                        main([option])

                self.assertEqual(cm.exception.code, 0)
                self.assertEqual(output.getvalue(), f"mermaid-timeline {__version__}\n")
                self.assertEqual(stderr.getvalue(), "")

    def test_cli_help_lists_version_option(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as cm:
                main(["-h"])

        self.assertEqual(cm.exception.code, 0)
        self.assertIn("-v, --version", output.getvalue())

    def test_cli_build_writes_interval_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_dir = tmp_path / "records" / "467.174-T-0100"
            input_dir.mkdir(parents=True)
            _write_jsonl(
                input_dir / "log_acquisition_records.467.174-T-0100.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "instrument_serial": "467.174-T-0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2023-11-20T10:00:00.000000Z",
                        "acquisition_state": "started",
                        "acquisition_evidence_kind": "transition",
                    },
                    {
                        "instrument_id": "T0100",
                        "instrument_serial": "467.174-T-0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2023-11-20T11:00:00.000000Z",
                        "acquisition_state": "stopped",
                        "acquisition_evidence_kind": "transition",
                    },
                ],
            )
            _write_jsonl(
                input_dir / "mer_event_records.467.174-T-0100.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "instrument_serial": "467.174-T-0100",
                        "source_file": "0100_event.MER",
                        "date": "2024-02-07T22:47:22.000000Z",
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
            stderr = io.StringIO()
            with redirect_stdout(output), redirect_stderr(stderr):
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
            self.assertEqual(output.getvalue(), "")
            self.assertNotIn('"buffer_intervals"', stderr.getvalue())
            self.assertIn(f"Done: intervals written to {output_root}", stderr.getvalue())
            output_dir = output_root / "467.174-T-0100"
            buffer_text = (output_dir / "buffer_intervals.jsonl").read_text(
                encoding="utf-8"
            )
            detreq_text = (output_dir / "detreq_intervals.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                '"end_time":"2023-11-20T11:00:00.000000Z",'
                '"duration":3600.000000',
                buffer_text,
            )
            self.assertIn(
                '"end_time":"2024-02-07T22:47:22.050000Z",'
                '"duration":0.050000',
                detreq_text,
            )
            self.assertIsInstance(
                json.loads(buffer_text)["duration"],
                float,
            )
            self.assertIsInstance(
                json.loads(detreq_text)["duration"],
                float,
            )
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

    def test_cli_build_prints_per_instrument_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_dir = tmp_path / "records" / "467.174-T-0100"
            input_dir.mkdir(parents=True)
            _write_jsonl(
                input_dir / "log_acquisition_records.467.174-T-0100.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "instrument_serial": "467.174-T-0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2024-01-01T00:00:00Z",
                        "acquisition_state": "started",
                        "acquisition_evidence_kind": "transition",
                    },
                    {
                        "instrument_id": "T0100",
                        "instrument_serial": "467.174-T-0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2024-01-01T02:00:00Z",
                        "acquisition_state": "stopped",
                        "acquisition_evidence_kind": "transition",
                    },
                ],
            )
            _write_jsonl(
                input_dir / "mer_event_records.467.174-T-0100.jsonl",
                [
                    _event_row(
                        "2024-01-02T00:00:00Z",
                        criterion="STA/LTA",
                        snr="1.0",
                        trig="0.1",
                        detrig="0.2",
                        length="3601",
                    ),
                    _event_row("2024-01-03T00:00:00Z", length="1801"),
                ],
            )

            output = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(output), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "build",
                        "--input",
                        str(tmp_path / "records"),
                        "--output",
                        str(tmp_path / "timeline"),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue().count("Building intervals..."), 1)
            self.assertIn("467.174-T-0100:", stderr.getvalue())
            self.assertRegex(
                stderr.getvalue(),
                r"buf: +1 intervals \[2\.0 hr\]\n"
                r"    det: +1 intervals \[1\.0 hr\]\n"
                r"    req: +1 intervals \[0\.5 hr\]",
            )
            self.assertIn("\nSummary:", stderr.getvalue())
            self.assertEqual(output.getvalue(), "")

    def test_cli_build_progress_falls_back_to_input_directory_name(self) -> None:
        summary = TimelinePipelineSummary(
            directories=[
                TimelineDirectorySummary(
                    input_dir=Path("foo/bar/baz"),
                    output_dir=Path("out/baz"),
                    buffer_intervals=0,
                    detreq_intervals=0,
                    summary_intervals=1,
                    diagnostics=0,
                    summary_interval_rows=[
                        {
                            "instrument_id": "T0100",
                            "instrument_serial": None,
                            "bin_size": "year",
                            "interval_count": {"buf": 0, "det": 0, "req": 0},
                            "duration_seconds": {"buf": 0.0, "det": 0.0, "req": 0.0},
                        }
                    ],
                )
            ]
        )
        output = io.StringIO()
        stderr = io.StringIO()

        def fake_run_timeline_pipeline(*args: object, **kwargs: object) -> object:
            del args
            progress_callback = kwargs["progress_callback"]
            progress_callback(summary.directories[0])
            return summary

        with patch(
            "mermaid_timeline.cli.run_timeline_pipeline",
            side_effect=fake_run_timeline_pipeline,
        ):
            with redirect_stdout(output), redirect_stderr(stderr):
                exit_code = main(
                    ["build", "--input", "records", "--output", "timeline"]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("baz:", stderr.getvalue())
        self.assertIn("\nSummary:", stderr.getvalue())
        self.assertEqual(output.getvalue(), "")

    def test_cli_build_progress_uses_summary_rows(self) -> None:
        summary = TimelinePipelineSummary(
            directories=[
                TimelineDirectorySummary(
                    input_dir=Path("records/not-the-label"),
                    output_dir=Path("timeline/not-the-label"),
                    buffer_intervals=99,
                    detreq_intervals=99,
                    summary_intervals=1,
                    diagnostics=0,
                    summary_interval_rows=[
                        {
                            "instrument_id": "T0100",
                            "instrument_serial": "467.174-T-0100",
                            "bin_size": "year",
                            "interval_count": {"buf": 2, "det": 3, "req": 4},
                            "duration_seconds": {
                                "buf": 7200.0,
                                "det": 10800.0,
                                "req": 14400.0,
                            },
                        }
                    ],
                ),
                TimelineDirectorySummary(
                    input_dir=Path("records/second-label"),
                    output_dir=Path("timeline/second-label"),
                    buffer_intervals=100,
                    detreq_intervals=100,
                    summary_intervals=1,
                    diagnostics=0,
                    summary_interval_rows=[
                        {
                            "instrument_id": "T0200",
                            "instrument_serial": "467.175-T-0200",
                            "bin_size": "year",
                            "interval_count": {"buf": 1234, "det": 6, "req": 7},
                            "duration_seconds": {
                                "buf": 36018000.0,
                                "det": 21600.0,
                                "req": 25200.0,
                            },
                        }
                    ],
                ),
            ]
        )
        output = io.StringIO()
        stderr = io.StringIO()

        def fake_run_timeline_pipeline(*args: object, **kwargs: object) -> object:
            del args
            self.assertEqual(stderr.getvalue(), "Building intervals...\n")
            progress_callback = kwargs["progress_callback"]
            for directory in summary.directories:
                progress_callback(directory)
            return summary

        with patch(
            "mermaid_timeline.cli.run_timeline_pipeline",
            side_effect=fake_run_timeline_pipeline,
        ):
            with redirect_stdout(output), redirect_stderr(stderr):
                exit_code = main(
                    ["build", "--input", "records", "--output", "timeline"]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("    buf:      2 intervals [2.0 hr]", stderr.getvalue())
        self.assertIn("    det:      3 intervals [3.0 hr]", stderr.getvalue())
        self.assertIn("    req:      4 intervals [4.0 hr]", stderr.getvalue())
        self.assertIn("    buf:  1,234 intervals [10,005.0 hr]", stderr.getvalue())
        self.assertIn("Done: intervals written to timeline", stderr.getvalue())
        self.assertIn("\nSummary:", stderr.getvalue())
        self.assertIn("    buf:     1,236 intervals [10,007.0 hr]", stderr.getvalue())
        self.assertIn("    det:         9 intervals [9.0 hr]", stderr.getvalue())
        self.assertIn("    req:        11 intervals [11.0 hr]", stderr.getvalue())
        self.assertEqual(output.getvalue(), "")

    def test_cli_build_defaults_paths_to_mermaid_records_and_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_dir = tmp_path / "records" / "467.174-T-0100"
            input_dir.mkdir(parents=True)
            _write_jsonl(
                input_dir / "log_acquisition_records.467.174-T-0100.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "instrument_serial": "467.174-T-0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2023-11-20T10:00:00.000000Z",
                        "acquisition_state": "started",
                        "acquisition_evidence_kind": "transition",
                    },
                    {
                        "instrument_id": "T0100",
                        "instrument_serial": "467.174-T-0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2023-11-20T11:00:00.000000Z",
                        "acquisition_state": "stopped",
                        "acquisition_evidence_kind": "transition",
                    }
                ],
            )

            output = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, {"MERMAID": str(tmp_path)}):
                with redirect_stdout(output), redirect_stderr(stderr):
                    exit_code = main(["build"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(output.getvalue(), "")
            self.assertTrue(
                (
                    tmp_path
                    / "timeline"
                    / "467.174-T-0100"
                    / "buffer_intervals.jsonl"
                ).exists()
            )

    def test_cli_build_defaults_output_to_mermaid_timeline_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_dir = tmp_path / "input-records" / "467.174-T-0100"
            input_dir.mkdir(parents=True)
            _write_jsonl(
                input_dir / "log_acquisition_records.467.174-T-0100.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "instrument_serial": "467.174-T-0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2023-11-20T10:00:00.000000Z",
                        "acquisition_state": "started",
                        "acquisition_evidence_kind": "transition",
                    },
                    {
                        "instrument_id": "T0100",
                        "instrument_serial": "467.174-T-0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2023-11-20T11:00:00.000000Z",
                        "acquisition_state": "stopped",
                        "acquisition_evidence_kind": "transition",
                    }
                ],
            )

            output = io.StringIO()
            stderr = io.StringIO()
            with patch.dict(os.environ, {"MERMAID": str(tmp_path)}):
                with redirect_stdout(output), redirect_stderr(stderr):
                    exit_code = main(
                        ["build", "--input", str(tmp_path / "input-records")]
                    )

            self.assertEqual(exit_code, 0)
            self.assertEqual(output.getvalue(), "")
            self.assertTrue(
                (
                    tmp_path
                    / "timeline"
                    / "467.174-T-0100"
                    / "buffer_intervals.jsonl"
                ).exists()
            )

    def test_cli_build_reports_missing_mermaid_for_default_paths(self) -> None:
        output = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(output), redirect_stderr(stderr):
                exit_code = main(["build"])

        self.assertEqual(exit_code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("$MERMAID is not set", stderr.getvalue())

    def test_cli_permissive_mode_writes_diagnostics_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_dir = tmp_path / "records" / "467.174-T-0100"
            input_dir.mkdir(parents=True)
            _write_jsonl(
                input_dir / "log_acquisition_records.467.174-T-0100.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "instrument_serial": "467.174-T-0100",
                        "source_file": "0100_acq.LOG",
                        "record_time": "2023-11-20T10:00:00.000000Z",
                        "acquisition_state": "stopped",
                        "acquisition_evidence_kind": "transition",
                    }
                ],
            )

            output_root = tmp_path / "timeline"
            output = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(output), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "build",
                        "--input",
                        str(tmp_path / "records"),
                        "--output",
                        str(output_root),
                        "--validation",
                        "permissive",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(output.getvalue(), "")

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
                        "records_file": "log_acquisition_records.467.174-T-0100.jsonl",
                        "input_file": str(
                            (
                                input_dir
                                / "log_acquisition_records.467.174-T-0100.jsonl"
                            ).resolve()
                        ),
                        "record_line": 1,
                        "issue_time": "2023-11-20T10:00:00.000000Z",
                        "instrument_id": "T0100",
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
        self.assertIn("$MERMAID/timeline", output.getvalue())
        self.assertNotIn("-i INPUT, --input INPUT", output.getvalue())

    def test_cli_plot_help_succeeds(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as cm:
                main(["plot", "--help"])

        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--input", output.getvalue())
        self.assertIn("--combined", output.getvalue())
        self.assertIn("--id", output.getvalue())
        self.assertIn("--ser", output.getvalue())
        self.assertNotIn("--instrument-id", output.getvalue())
        self.assertNotIn("--instrument-serial", output.getvalue())
        self.assertIn("-i, --input INPUT", output.getvalue())
        self.assertIn("-s, --start-time START_TIME", output.getvalue())
        self.assertIn("-e, --end-time END_TIME", output.getvalue())
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
                        "duration": 1.0,
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
            self.assertIn("duration_seconds", html)
            self.assertIn("1.000000", html)
            self.assertIn("null", html)
            self.assertIn("float_serial: 467.174", html)
            self.assertIn("timeline_subdir: 467.174-T-0100", html)
            self.assertIn("open-ended; true end unknown", html)

    def test_plot_renders_hoverable_interval_bars_with_detreq_lane(self) -> None:
        figure = _build_figure(
            [
                _interval_row("T0100", "det", "2024-02-07T22:47:22Z"),
                _interval_row("T0100", "req", "2024-02-07T22:48:22Z"),
                _interval_row(
                    "T0100",
                    "buf",
                    "2024-02-07T22:49:22Z",
                    metadata={"start_evidence_kind": "transition"},
                ),
            ],
            _FakeGo,
        )

        self.assertEqual([trace.name for trace in figure.data], ["buf", "req", "det"])
        self.assertEqual([trace.orientation for trace in figure.data], ["h"] * 3)
        self.assertEqual([trace.y for trace in figure.data], [[0.06], [-0.06], [-0.06]])
        self.assertEqual([trace.width for trace in figure.data], [0.12] * 3)
        self.assertEqual(
            [trace.base for trace in figure.data],
            [
                [datetime.fromisoformat("2024-02-07T22:49:22+00:00")],
                [datetime.fromisoformat("2024-02-07T22:48:22+00:00")],
                [datetime.fromisoformat("2024-02-07T22:47:22+00:00")],
            ],
        )
        self.assertEqual([trace.x for trace in figure.data], [[1000.0]] * 3)
        self.assertEqual(
            [trace.marker["color"] for trace in figure.data],
            ["#000000", "#D627B0", "#1F77B4"],
        )
        self.assertTrue(
            all("duration_seconds" in trace.hovertemplate for trace in figure.data)
        )
        self.assertTrue(
            all("<extra></extra>" in trace.hovertemplate for trace in figure.data)
        )
        self.assertIn("buf", figure.data[0].customdata[0])
        self.assertIn("T0100", figure.data[0].customdata[0])
        self.assertIn("1.000000", figure.data[0].customdata[0])
        self.assertIn("transition", figure.data[0].customdata[0])
        self.assertIn("start_evidence_kind", figure.data[0].hovertemplate)
        self.assertEqual([trace.legendrank for trace in figure.data], [2, 1, 0])
        self.assertEqual(figure.layout["xaxis"]["type"], "date")
        self.assertEqual(figure.layout["xaxis"]["title"], "Time")
        self.assertEqual(figure.layout["yaxis"]["type"], "linear")
        self.assertEqual(figure.layout["yaxis"]["tickmode"], "array")
        self.assertEqual(figure.layout["yaxis"]["tickvals"], [0.0])
        self.assertEqual(figure.layout["yaxis"]["ticktext"], ["T0100"])
        self.assertEqual(figure.layout["yaxis"]["range"], [0.5, -0.5])
        self.assertEqual(figure.layout["barmode"], "overlay")
        self.assertNotIn("yaxis2", figure.layout)
        self.assertNotIn("yaxis3", figure.layout)
        self.assertEqual(figure.layout["yaxis"]["title"], "Instrument ID")

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
            self.assertEqual(summary["intervals"], 3)
            self.assertEqual(summary["reports"], 3)
            self.assertEqual(
                {Path(item["output"]).resolve() for item in summary["outputs"]},
                {
                    first_report.resolve(),
                    second_report.resolve(),
                    nested_report.resolve(),
                },
            )
            self.assertIn("input directories", stderr.getvalue())
            first_html = first_report.read_text(encoding="utf-8")
            second_html = second_report.read_text(encoding="utf-8")
            nested_html = nested_report.read_text(encoding="utf-8")
            self.assertIn("R0065", first_html)
            self.assertNotIn("T0100", first_html)
            self.assertIn("T0100", second_html)
            self.assertNotIn("R0065", second_html)
            self.assertIn("T9999", nested_html)

    def test_cli_plot_output_directory_mirrors_recursive_input_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            first_dir = tmp_path / "timeline" / "batch-a" / "467.174-T-0100"
            second_dir = tmp_path / "timeline" / "batch-b" / "467.175-T-0200"
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
                    }
                ],
            )
            _write_jsonl(
                second_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "T0200",
                        "interval_type": "req",
                        "start_time": "2024-03-07T22:47:22Z",
                        "end_time": "2024-03-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    }
                ],
            )

            output_root = tmp_path / "reports"
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
                        str(output_root),
                    ]
                )

            first_report = (
                output_root
                / "batch-a"
                / "467.174-T-0100"
                / "T0100_data_intervals.html"
            )
            second_report = (
                output_root
                / "batch-b"
                / "467.175-T-0200"
                / "T0200_data_intervals.html"
            )
            summary = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(
                {Path(item["output"]).resolve() for item in summary["outputs"]},
                {first_report.resolve(), second_report.resolve()},
            )
            self.assertIn("T0100", first_report.read_text(encoding="utf-8"))
            self.assertIn("T0200", second_report.read_text(encoding="utf-8"))

    def test_cli_plot_accepts_single_instrument_serial_input_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_dir = tmp_path / "timeline" / "452.020-P-21"
            _write_jsonl(
                input_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "P0021",
                        "interval_type": "det",
                        "start_time": "2024-02-07T22:47:22Z",
                        "end_time": "2024-02-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    }
                ],
            )

            report_path = tmp_path / "reports" / "P0021_data_intervals.html"
            output = io.StringIO()
            with patch(
                "mermaid_timeline.plotting._load_plotly",
                return_value=(_FakeGo, _fake_plot),
            ), redirect_stdout(output):
                exit_code = main(
                    [
                        "plot",
                        "--input",
                        str(input_dir),
                        "--output",
                        str(report_path),
                    ]
                )

            summary = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["intervals"], 1)
            self.assertEqual(summary["reports"], 1)
            self.assertEqual(summary["outputs"][0]["instrument_id"], "P0021")
            self.assertEqual(summary["outputs"][0]["output"], str(report_path))
            self.assertIn("P0021", report_path.read_text(encoding="utf-8"))

    def test_cli_plot_single_instrument_input_rejects_mismatched_selector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_dir = tmp_path / "timeline" / "452.020-P-21"
            _write_jsonl(
                input_dir / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "P0021",
                        "interval_type": "det",
                        "start_time": "2024-02-07T22:47:22Z",
                        "end_time": "2024-02-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    }
                ],
            )

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "plot",
                        "--input",
                        str(input_dir),
                        "--id",
                        "P0022",
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertIn("does not match input serial directory", stderr.getvalue())

    def test_cli_plot_reports_no_interval_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(["plot", "--input", tmp_name])

            self.assertEqual(exit_code, 1)
            self.assertIn("no interval JSONL files found", stderr.getvalue())

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
                        "--id",
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
                        "--ser",
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
                        "--id",
                        "0100",
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertIn("5-character station name", stderr.getvalue())

    def test_cli_plot_instrument_id_reports_multiple_serial_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            _write_jsonl(
                tmp_path
                / "timeline"
                / "batch-a"
                / "467.174-T-0100"
                / "detreq_intervals.jsonl",
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
                tmp_path
                / "timeline"
                / "batch-b"
                / "999.999-T-0100"
                / "detreq_intervals.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "interval_type": "req",
                        "start_time": "2024-03-07T22:47:22Z",
                        "end_time": "2024-03-07T22:47:23Z",
                        "start_boundary": "closed",
                        "end_boundary": "closed",
                    },
                ],
            )

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "plot",
                        "--input",
                        str(tmp_path / "timeline"),
                        "--id",
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
                        "-s",
                        "2024-03-01T00:00:00Z",
                        "-e",
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
                        "--validation",
                        "strict",
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
                        "--validation",
                        "strict",
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


def _event_row(
    date: str,
    *,
    criterion: str | None = None,
    snr: str | None = None,
    trig: str | None = None,
    detrig: str | None = None,
    length: str = "2",
) -> dict[str, object]:
    return {
        "instrument_id": "T0100",
        "instrument_serial": "467.174-T-0100",
        "source_file": "0100_event.MER",
        "date": date,
        "criterion": criterion,
        "snr": snr,
        "trig": trig,
        "detrig": detrig,
        "sampling_rate": "1.000000",
        "length": length,
    }


def _interval_row(
    instrument_id: str,
    interval_type: str,
    start_time: str,
    *,
    metadata: dict[str, object] | None = None,
) -> IntervalRow:
    parsed_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    parsed_end = parsed_start + timedelta(seconds=1)
    return IntervalRow(
        instrument_id=instrument_id,
        interval_type=interval_type,
        start_time=parsed_start,
        end_time=parsed_end,
        start_time_text=start_time,
        end_time_text=start_time,
        duration=1.0,
        start_boundary="closed",
        end_boundary="closed",
        metadata=metadata or {},
        provenance={},
        interval_file=Path("intervals.jsonl"),
        interval_line=1,
        timeline_subdir=None,
        float_serial=None,
    )


class _FakeTrace:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class _FakeFigure:
    def __init__(self) -> None:
        self.data: list[_FakeTrace] = []
        self.layout: dict[str, object] = {}

    def add_trace(self, trace: _FakeTrace) -> None:
        self.data.append(trace)

    def update_layout(self, **kwargs: object) -> None:
        self.layout.update(kwargs)

    def update_yaxes(self, **_: object) -> None:
        return None


class _FakeGo:
    Figure = _FakeFigure
    Bar = _FakeTrace


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
        chunks.append(str(trace.hovertemplate))
        for values in trace.customdata:
            chunks.extend(str(item) for item in values)
            for index, value in enumerate(values):
                token = f"%{{customdata[{index}]}}"
                for line in str(trace.hovertemplate).split("<br>"):
                    if token in line:
                        chunks.append(line.replace(token, str(value)))
                        break
    return "\n".join(chunks)


if __name__ == "__main__":
    unittest.main()
