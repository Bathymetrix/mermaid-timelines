from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from mermaid_timeline.cli import main


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

    def test_cli_accepts_synthesize_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp_path = Path(tmp_name)
            input_root = tmp_path / "records"
            input_root.mkdir()

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "synthesize",
                        "--input-root",
                        str(input_root),
                        "--output-root",
                        str(tmp_path / "timeline"),
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "buffer_intervals": 0,
                "detreq_intervals": 0,
                "diagnostics": 0,
                "directories": 0,
            },
        )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
