from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mermaid_timeline.pipeline import (
    SUMMARY_INTERVALS_FILE,
    _discover_record_dirs,
    _record_filename_parts,
    _record_files_for_family,
    synthesize_directory,
)


class PipelineTests(unittest.TestCase):
    def test_record_filename_parts_preserves_dotted_instrument_serial(self) -> None:
        self.assertEqual(
            _record_filename_parts("log_operational_records.467.174-T-0100.jsonl"),
            ("log_operational_records", "467.174-T-0100"),
        )
        self.assertEqual(
            _record_filename_parts("mer_event_records.465.152-R-0001.jsonl"),
            ("mer_event_records", "465.152-R-0001"),
        )

    def test_record_filename_parts_accepts_legacy_unsuffixed_name(self) -> None:
        self.assertEqual(
            _record_filename_parts("log_acquisition_records.jsonl"),
            ("log_acquisition_records", None),
        )

    def test_discover_record_dirs_includes_mixed_v1_and_v2_directories(self) -> None:
        with TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            v1_dir = root / "legacy"
            v2_dir = root / "467.174-T-0100"
            v1_dir.mkdir()
            v2_dir.mkdir()
            (v1_dir / "log_acquisition_records.jsonl").write_text("", encoding="utf-8")
            (v2_dir / "mer_event_records.467.174-T-0100.jsonl").write_text(
                "", encoding="utf-8"
            )

            self.assertEqual(_discover_record_dirs(root), [v2_dir, v1_dir])

    def test_record_files_for_family_prefers_v2_suffixed_files(self) -> None:
        with TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            legacy = root / "log_acquisition_records.jsonl"
            suffixed = root / "log_acquisition_records.467.174-T-0100.jsonl"
            legacy.write_text("", encoding="utf-8")
            suffixed.write_text("", encoding="utf-8")

            self.assertEqual(
                _record_files_for_family(root, "log_acquisition_records"), [suffixed]
            )

    def test_synthesize_directory_writes_summary_intervals_jsonl(self) -> None:
        with TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            input_dir = root / "records" / "467.174-T-0100"
            output_dir = root / "timeline" / "467.174-T-0100"
            input_dir.mkdir(parents=True)
            _write_jsonl(
                input_dir / "log_acquisition_records.467.174-T-0100.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "record_time": "2024-01-02T00:00:00Z",
                        "acquisition_state": "started",
                        "acquisition_evidence_kind": "transition",
                    },
                    {
                        "instrument_id": "T0100",
                        "record_time": "2024-01-02T01:00:00Z",
                        "acquisition_state": "stopped",
                        "acquisition_evidence_kind": "transition",
                    },
                ],
            )

            summary = synthesize_directory(input_dir, output_dir)

            rows = _read_jsonl(output_dir / SUMMARY_INTERVALS_FILE)
            self.assertGreater(summary.summary_intervals, 0)
            self.assertEqual(summary.summary_intervals, len(rows))
            day_rows = [row for row in rows if row["bin_size"] == "day"]
            self.assertEqual(len(day_rows), 1)
            self.assertEqual(day_rows[0]["duration_seconds"]["buf"], 3600.0)
            self.assertEqual(day_rows[0]["instrument_serial"], "467.174-T-0100")

    def test_summary_intervals_emit_fixed_precision_numeric_durations(self) -> None:
        with TemporaryDirectory() as tmp_name:
            root = Path(tmp_name)
            input_dir = root / "records" / "467.174-T-0100"
            output_dir = root / "timeline" / "467.174-T-0100"
            input_dir.mkdir(parents=True)
            _write_jsonl(
                input_dir / "log_acquisition_records.467.174-T-0100.jsonl",
                [
                    {
                        "instrument_id": "T0100",
                        "record_time": "2024-01-01T00:00:00Z",
                        "acquisition_state": "started",
                        "acquisition_evidence_kind": "transition",
                    },
                    {
                        "instrument_id": "T0100",
                        "record_time": "2024-01-08T00:00:00Z",
                        "acquisition_state": "stopped",
                        "acquisition_evidence_kind": "transition",
                    },
                ],
            )

            synthesize_directory(input_dir, output_dir)

            path = output_dir / SUMMARY_INTERVALS_FILE
            text = path.read_text(encoding="utf-8")
            rows = _read_jsonl(path)
            self.assertNotRegex(text, r"-?\d+(?:\.\d+)?[eE][+-]?\d+")
            self.assertIn('"buf":604800.000000', text)
            for field_name in ("duration_seconds", "duration_fraction"):
                sections = re.findall(rf'"{field_name}":\{{([^}}]+)\}}', text)
                self.assertGreater(len(sections), 0)
                for section in sections:
                    values = re.findall(r':(-?\d+\.\d+)', section)
                    self.assertEqual(len(values), 3)
                    for value in values:
                        self.assertRegex(value, r"^-?\d+\.\d{6}$")

            for row in rows:
                for field_name in ("duration_seconds", "duration_fraction"):
                    for value in row[field_name].values():
                        self.assertIsInstance(value, float)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(row)}\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    unittest.main()
