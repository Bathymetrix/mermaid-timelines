from __future__ import annotations

import unittest

from mermaid_timeline.buffer import build_buffer_intervals
from mermaid_timeline.diagnostics import TimelineValidationError


def row(
    record_time: str,
    state: str,
    evidence_kind: str,
    *,
    instrument_id: str = "0100",
    source_file: str = "0100_acq.LOG",
) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "source_file": source_file,
        "record_time": record_time,
        "acquisition_state": state,
        "acquisition_evidence_kind": evidence_kind,
    }


class BufferTests(unittest.TestCase):
    def test_started_assertion_then_stopped_transition_is_closed_interval(self) -> None:
        result = build_buffer_intervals(
            [
                row("2023-11-20T10:00:00", "started", "assertion"),
                row("2023-11-20T12:45:10", "stopped", "transition"),
            ]
        )

        self.assertEqual(len(result.intervals), 1)
        interval = result.intervals[0]
        self.assertEqual(interval["start_time"], "2023-11-20T10:00:00.000000Z")
        self.assertEqual(interval["end_time"], "2023-11-20T12:45:10.000000Z")
        self.assertEqual(interval["start_boundary"], "closed")
        self.assertEqual(interval["end_boundary"], "closed")
        self.assertEqual(interval["start_evidence_kind"], "assertion")
        self.assertEqual(interval["end_evidence_kind"], "transition")

    def test_started_transition_then_stopped_assertion_keeps_end_open(self) -> None:
        result = build_buffer_intervals(
            [
                row("2023-11-20T10:00:00", "started", "transition"),
                row("2023-11-20T12:45:10", "stopped", "assertion"),
            ]
        )

        self.assertEqual(len(result.intervals), 1)
        interval = result.intervals[0]
        self.assertEqual(interval["start_time"], "2023-11-20T10:00:00.000000Z")
        self.assertIsNone(interval["end_time"])
        self.assertEqual(interval["end_boundary"], "open_unknown")
        self.assertEqual(interval["end_evidence_kind"], "assertion")
        self.assertEqual(
            interval["end_evidence_time"], "2023-11-20T12:45:10.000000Z"
        )

    def test_repeated_stopped_assertions_do_not_create_intervals(self) -> None:
        result = build_buffer_intervals(
            [
                row("2023-11-20T10:00:00", "stopped", "assertion"),
                row("2023-11-20T12:45:10", "stopped", "assertion"),
            ]
        )

        self.assertEqual(result.intervals, [])
        self.assertEqual(result.diagnostics, [])

    def test_assertion_inside_transition_interval_does_not_split_interval(self) -> None:
        result = build_buffer_intervals(
            [
                row("2023-11-20T10:00:00", "started", "transition"),
                row("2023-11-20T11:00:00", "started", "assertion"),
                row("2023-11-20T12:45:10", "stopped", "transition"),
            ]
        )

        self.assertEqual(len(result.intervals), 1)
        interval = result.intervals[0]
        self.assertEqual(interval["start_time"], "2023-11-20T10:00:00.000000Z")
        self.assertEqual(interval["end_time"], "2023-11-20T12:45:10.000000Z")
        self.assertEqual(interval["provenance"]["start_record_line"], 1)
        self.assertEqual(interval["provenance"]["end_record_line"], 3)

    def test_duplicate_transition_is_strict_error_and_diagnostic_warning(self) -> None:
        rows = [
            row("2023-11-20T10:00:00", "started", "transition"),
            row("2023-11-20T10:05:00", "started", "transition"),
            row("2023-11-20T12:45:10", "stopped", "transition"),
        ]

        with self.assertRaisesRegex(
            TimelineValidationError, "duplicate_start_transition"
        ):
            build_buffer_intervals(rows, validation="strict")

        diagnostic = build_buffer_intervals(rows, validation="diagnostic")
        self.assertEqual(len(diagnostic.intervals), 1)
        self.assertEqual(
            [item.code for item in diagnostic.diagnostics],
            ["duplicate_start_transition"],
        )
        self.assertEqual(
            [item.issue_time for item in diagnostic.diagnostics],
            ["2023-11-20T10:05:00.000000Z"],
        )

    def test_orphan_stop_transition_is_strict_error_and_diagnostic_warning(self) -> None:
        rows = [row("2023-11-20T10:00:00", "stopped", "transition")]

        with self.assertRaisesRegex(TimelineValidationError, "orphan_stop_transition"):
            build_buffer_intervals(rows, validation="strict")

        diagnostic = build_buffer_intervals(rows, validation="diagnostic")
        self.assertEqual(diagnostic.intervals, [])
        self.assertEqual(
            [item.code for item in diagnostic.diagnostics],
            ["orphan_stop_transition"],
        )
        self.assertEqual(
            [item.issue_time for item in diagnostic.diagnostics],
            ["2023-11-20T10:00:00.000000Z"],
        )

    def test_orphan_stop_transition_diagnostic_mode_continues(self) -> None:
        rows = [
            row("2023-11-20T10:00:00", "stopped", "transition"),
            row("2023-11-20T11:00:00", "started", "transition"),
            row("2023-11-20T12:00:00", "stopped", "transition"),
        ]

        with self.assertRaisesRegex(TimelineValidationError, "orphan_stop_transition"):
            build_buffer_intervals(rows, validation="strict")

        diagnostic = build_buffer_intervals(rows, validation="diagnostic")
        self.assertEqual(
            [item.code for item in diagnostic.diagnostics],
            ["orphan_stop_transition"],
        )
        self.assertEqual(len(diagnostic.intervals), 1)
        self.assertEqual(
            diagnostic.intervals[0]["start_time"], "2023-11-20T11:00:00.000000Z"
        )
        self.assertEqual(
            diagnostic.intervals[0]["end_time"], "2023-11-20T12:00:00.000000Z"
        )

    def test_offset_record_time_is_converted_to_utc(self) -> None:
        result = build_buffer_intervals(
            [
                row("2023-11-20T10:00:00-08:00", "started", "transition"),
                row("2023-11-20T11:00:00-08:00", "stopped", "transition"),
            ]
        )

        interval = result.intervals[0]
        self.assertEqual(interval["start_time"], "2023-11-20T18:00:00.000000Z")
        self.assertEqual(interval["end_time"], "2023-11-20T19:00:00.000000Z")

    def test_open_interval_at_end_of_input_is_open_unknown(self) -> None:
        result = build_buffer_intervals(
            [row("2023-11-20T10:00:00", "started", "transition")]
        )

        self.assertEqual(len(result.intervals), 1)
        interval = result.intervals[0]
        self.assertIsNone(interval["end_time"])
        self.assertEqual(interval["end_boundary"], "open_unknown")
        self.assertIsNone(interval["end_evidence_kind"])


if __name__ == "__main__":
    unittest.main()
