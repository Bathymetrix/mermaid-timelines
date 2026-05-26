from __future__ import annotations

import unittest

from mermaid_timeline.records import source_records
from mermaid_timeline.schema import SCHEMA_VERSION
from mermaid_timeline.summary import (
    BINNING_POLICY,
    OVERLAP_POLICY,
    build_summary_intervals,
)


def interval_row(
    interval_type: str,
    start_time: str,
    end_time: str | None,
    *,
    instrument_id: str = "T0100",
    records_file: str = "buffer_intervals.467.174-T-0100.jsonl",
) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "interval_type": interval_type,
        "start_time": start_time,
        "end_time": end_time,
        "start_boundary": "closed",
        "end_boundary": "closed",
        "provenance": {"records_file": records_file},
    }


def summary_row(
    rows: list[dict[str, object]],
    bin_size: str,
    bin_start_time: str,
) -> dict[str, object]:
    summaries = build_summary_intervals(source_records(rows))
    for row in summaries:
        if row["bin_size"] == bin_size and row["bin_start_time"] == bin_start_time:
            return row
    raise AssertionError(f"missing {bin_size} summary row for {bin_start_time}")


class SummaryTests(unittest.TestCase):
    def test_interval_fully_inside_daily_bin(self) -> None:
        row = summary_row(
            [
                interval_row(
                    "buf",
                    "2024-01-02T01:00:00Z",
                    "2024-01-02T02:00:00Z",
                )
            ],
            "day",
            "2024-01-02T00:00:00.000000Z",
        )

        self.assertEqual(
            row["duration_seconds"], {"buf": 3600.0, "det": 0.0, "req": 0.0}
        )
        self.assertEqual(row["interval_count"], {"buf": 1, "det": 0, "req": 0})
        self.assertEqual(row["duration_fraction"]["buf"], 0.041667)
        self.assertEqual(row["schema_version"], SCHEMA_VERSION)
        self.assertEqual(row["instrument_serial"], "467.174-T-0100")
        self.assertEqual(row["binning_policy"], BINNING_POLICY)
        self.assertEqual(row["overlap_policy"], OVERLAP_POLICY)

    def test_interval_crossing_day_boundary_is_clipped(self) -> None:
        rows = [
            interval_row("buf", "2024-01-02T23:00:00Z", "2024-01-03T01:30:00Z")
        ]

        first = summary_row(rows, "day", "2024-01-02T00:00:00.000000Z")
        second = summary_row(rows, "day", "2024-01-03T00:00:00.000000Z")

        self.assertEqual(first["duration_seconds"]["buf"], 3600.0)
        self.assertEqual(second["duration_seconds"]["buf"], 5400.0)
        self.assertEqual(first["interval_count"]["buf"], 1)
        self.assertEqual(second["interval_count"]["buf"], 1)

    def test_interval_crossing_week_boundary_is_clipped_to_monday_weeks(self) -> None:
        rows = [
            interval_row("det", "2023-12-31T12:00:00Z", "2024-01-01T12:00:00Z")
        ]

        first = summary_row(rows, "week", "2023-12-25T00:00:00.000000Z")
        second = summary_row(rows, "week", "2024-01-01T00:00:00.000000Z")

        self.assertEqual(first["duration_seconds"]["det"], 43200.0)
        self.assertEqual(second["duration_seconds"]["det"], 43200.0)

    def test_interval_crossing_month_boundary_is_clipped(self) -> None:
        rows = [
            interval_row("req", "2018-07-31T12:00:00Z", "2018-08-02T12:00:00Z")
        ]

        july = summary_row(rows, "month", "2018-07-01T00:00:00.000000Z")
        august = summary_row(rows, "month", "2018-08-01T00:00:00.000000Z")

        self.assertEqual(july["duration_seconds"]["req"], 12 * 3600.0)
        self.assertEqual(august["duration_seconds"]["req"], 36 * 3600.0)
        self.assertEqual(july["interval_count"]["req"], 1)
        self.assertEqual(august["interval_count"]["req"], 1)

    def test_interval_crossing_year_boundary_is_clipped(self) -> None:
        rows = [
            interval_row("buf", "2023-12-31T12:00:00Z", "2024-01-01T12:00:00Z")
        ]

        first = summary_row(rows, "year", "2023-01-01T00:00:00.000000Z")
        second = summary_row(rows, "year", "2024-01-01T00:00:00.000000Z")

        self.assertEqual(first["duration_seconds"]["buf"], 43200.0)
        self.assertEqual(second["duration_seconds"]["buf"], 43200.0)

    def test_det_req_buf_aggregation_remains_separate(self) -> None:
        row = summary_row(
            [
                interval_row("buf", "2024-01-02T00:00:00Z", "2024-01-02T01:00:00Z"),
                interval_row("det", "2024-01-02T00:00:00Z", "2024-01-02T02:00:00Z"),
                interval_row("req", "2024-01-02T00:00:00Z", "2024-01-02T03:00:00Z"),
            ],
            "day",
            "2024-01-02T00:00:00.000000Z",
        )

        self.assertEqual(
            row["duration_seconds"],
            {"buf": 3600.0, "det": 7200.0, "req": 10800.0},
        )
        self.assertNotIn("total", row)
        self.assertNotIn("total", row["duration_seconds"])

    def test_same_type_overlaps_are_summed_and_fraction_can_exceed_one(self) -> None:
        row = summary_row(
            [
                interval_row("req", "2024-01-02T00:00:00Z", "2024-01-03T00:00:00Z"),
                interval_row("req", "2024-01-02T00:00:00Z", "2024-01-03T00:00:00Z"),
            ],
            "day",
            "2024-01-02T00:00:00.000000Z",
        )

        self.assertEqual(row["duration_seconds"]["req"], 172800.0)
        self.assertEqual(row["interval_count"]["req"], 2)
        self.assertEqual(row["duration_fraction"]["req"], 2.0)

    def test_pathological_1970_timestamps_are_summarized_normally(self) -> None:
        row = summary_row(
            [
                interval_row(
                    "det",
                    "1970-01-01T00:00:00Z",
                    "1970-01-01T00:10:00Z",
                )
            ],
            "year",
            "1970-01-01T00:00:00.000000Z",
        )

        self.assertEqual(row["bin_start_time"], "1970-01-01T00:00:00.000000Z")
        self.assertEqual(row["duration_seconds"]["det"], 600.0)

    def test_emitted_field_order_is_stable(self) -> None:
        row = summary_row(
            [
                interval_row(
                    "buf",
                    "2024-01-02T01:00:00Z",
                    "2024-01-02T02:00:00Z",
                )
            ],
            "day",
            "2024-01-02T00:00:00.000000Z",
        )

        self.assertEqual(
            list(row),
            [
                "schema_version",
                "generated_by",
                "instrument_id",
                "instrument_serial",
                "bin_size",
                "bin_start_time",
                "bin_end_time",
                "duration_seconds",
                "interval_count",
                "duration_fraction",
                "binning_policy",
                "overlap_policy",
            ],
        )


if __name__ == "__main__":
    unittest.main()
