from __future__ import annotations

import unittest

from mermaid_timeline.detreq import build_detreq_intervals
from mermaid_timeline.diagnostics import TimelineValidationError


def event_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "instrument_id": "0007",
        "source_file": "0007_XXXXXXXX.MER",
        "date": "2018-07-12T06:49:56.429681",
        "criterion": None,
        "snr": None,
        "trig": None,
        "detrig": None,
        "sampling_rate": "20.0",
        "length": "4448",
    }
    row.update(overrides)
    return row


class DetReqTests(unittest.TestCase):
    def test_req_interval_uses_first_and_last_sample_times(self) -> None:
        result = build_detreq_intervals([event_row()])

        self.assertEqual(len(result.intervals), 1)
        interval = result.intervals[0]
        self.assertEqual(interval["interval_type"], "req")
        self.assertEqual(interval["start_time"], "2018-07-12T06:49:56.429681Z")
        self.assertEqual(interval["end_time"], "2018-07-12T06:53:38.779681Z")
        self.assertEqual(interval["sampling_rate_hz"], 20.0)
        self.assertEqual(interval["sample_count"], 4448)

    def test_det_interval_requires_all_detection_fields(self) -> None:
        result = build_detreq_intervals(
            [
                event_row(
                    criterion="0.0296122",
                    snr="2.556",
                    trig="2000",
                    detrig="5819",
                )
            ]
        )

        self.assertEqual(result.intervals[0]["interval_type"], "det")

    def test_mixed_detection_fields_are_validation_failures(self) -> None:
        rows = [event_row(criterion="0.0296122")]

        with self.assertRaisesRegex(TimelineValidationError, "mixed_detreq_fields"):
            build_detreq_intervals(rows)

        diagnostic = build_detreq_intervals(rows, validation="diagnostic")
        self.assertEqual(diagnostic.intervals, [])
        self.assertEqual(
            [item.code for item in diagnostic.diagnostics],
            ["mixed_detreq_fields"],
        )

    def test_single_sample_interval_has_equal_start_and_end(self) -> None:
        result = build_detreq_intervals([event_row(length="1")])

        interval = result.intervals[0]
        self.assertEqual(interval["start_time"], "2018-07-12T06:49:56.429681Z")
        self.assertEqual(interval["end_time"], "2018-07-12T06:49:56.429681Z")

    def test_offset_event_date_is_converted_to_utc(self) -> None:
        result = build_detreq_intervals(
            [event_row(date="2018-07-11T23:49:56.429681-07:00", length="1")]
        )

        interval = result.intervals[0]
        self.assertEqual(interval["start_time"], "2018-07-12T06:49:56.429681Z")
        self.assertEqual(interval["end_time"], "2018-07-12T06:49:56.429681Z")


if __name__ == "__main__":
    unittest.main()
