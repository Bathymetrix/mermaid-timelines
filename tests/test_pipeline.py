from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mermaid_timeline.pipeline import (
    _discover_record_dirs,
    _record_filename_parts,
    _record_files_for_family,
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


if __name__ == "__main__":
    unittest.main()
