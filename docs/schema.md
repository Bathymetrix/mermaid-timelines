# mermaid-timeline Schema

Current schema version: `0.2.0`

All products are JSONL streams. There is no top-level document wrapper.

## Versioning

`schema_version` tracks output-data compatibility. It is intentionally separate
from the `generated_by.version` package version, which tracks software releases.
Multiple `mermaid-timeline` package releases may emit the same schema version.

Schema changes should be intentional and semantically versioned. Bump the schema
major version for incompatible output changes. Additive, backward-compatible
fields may bump the schema minor version.

## Common Fields

Every interval record includes:

- `schema_version`
- `generated_by`
- `instrument_id`
- `interval_type`
- `start_time`
- `end_time`
- `duration`
- `start_boundary`
- `end_boundary`
- `provenance`

`duration` is the known interval duration in seconds, emitted as a JSON number
with exactly 6 decimal places. Open-ended BUF intervals with unknown `end_time`
emit `duration: null`.

Boundary vocabulary for `0.2.0`:

- `closed`: the interval boundary timestamp is included in the known interval.
- `open_unknown`: the true boundary is unknown and must not be inferred from the
  evidence timestamp.

`interval_type` vocabulary for `0.2.0`:

- `buf`: acquisition buffer interval synthesized from acquisition records.
- `det`: detected MER event interval.
- `req`: requested MER event interval without detection fields.

`provenance` is intentionally small and points back to the normalized JSONL row
or rows used to synthesize the interval. BUF intervals include
`records_file`, `start_record_line`, `end_record_line`, and `source_file`.
DET/REQ intervals include `records_file`, `record_line`, and `source_file`.

## Summary Intervals

Output: `summary_intervals.jsonl`

The summary stream emits one row per `instrument_id`, `bin_size`, and
`bin_start_time`. `bin_size` is one of `day`, `week`, `month`, or `year`.
Daily, monthly, and yearly bins use UTC calendar boundaries. Weekly bins use
ISO-style Monday-start UTC weeks.

Summary rows aggregate known BUF/DET/REQ durations from
`buffer_intervals.jsonl` and `detreq_intervals.jsonl`. Each source interval is
clipped into half-open bins, `[bin_start_time, bin_end_time)`, so an interval
crossing a boundary contributes only the overlap inside each bin. Intervals
with unknown `end_time` do not have a known duration and are not included in
duration totals.

BUF, DET, and REQ are strictly separate throughout aggregation. There is no
combined total duration field. Overlapping intervals are not unioned; durations
are summed independently within each interval type. Because of this,
`duration_fraction` may exceed `1.0` when same-type intervals overlap.

`interval_count` counts intervals of each type with nonzero clipped duration in
the bin. If one interval crosses two monthly bins, it increments the relevant
type count in both rows. Counts are diagnostic and are not necessarily additive
across bins.

Pathological timestamps, including clock-error-era values such as 1970 DET/REQ
intervals, are summarized normally. They are not repaired, reinterpreted, or
special-cased.

Summary shape:

```json
{
  "schema_version": "0.2.0",
  "generated_by": {
    "package": "mermaid-timeline",
    "version": "0.1.1"
  },
  "instrument_id": "T0100",
  "instrument_serial": "467.174-T-0100",
  "bin_size": "day",
  "bin_start_time": "2024-01-02T00:00:00.000000Z",
  "bin_end_time": "2024-01-03T00:00:00.000000Z",
  "duration_seconds": {
    "buf": 3600.000000,
    "det": 0.000000,
    "req": 0.000000
  },
  "interval_count": {
    "buf": 1,
    "det": 0,
    "req": 0
  },
  "duration_fraction": {
    "buf": 0.041667,
    "det": 0.000000,
    "req": 0.000000
  },
  "binning_policy": "clip_intervals_to_half_open_bins",
  "overlap_policy": "sum_durations_without_unioning_by_interval_type"
}
```

## BUF Intervals

Input: `log_acquisition_records.<instrument_serial>.jsonl`

Legacy unsuffixed `log_acquisition_records.jsonl` inputs are also accepted when
the suffixed v2 file is not present.

Required input fields:

- `instrument_id`
- `record_time`
- `acquisition_state`
- `acquisition_evidence_kind`

Output shape:

```json
{
  "schema_version": "0.2.0",
  "generated_by": {
    "package": "mermaid-timeline",
    "version": "0.1.1"
  },
  "instrument_id": "T0100",
  "interval_type": "buf",
  "start_time": "2023-11-20T10:00:00.000000Z",
  "end_time": null,
  "duration": null,
  "start_boundary": "closed",
  "end_boundary": "open_unknown",
  "start_evidence_kind": "transition",
  "end_evidence_kind": "assertion",
  "start_evidence_time": "2023-11-20T10:00:00.000000Z",
  "end_evidence_time": "2023-11-20T12:45:10.000000Z",
  "provenance": {
    "records_file": "log_acquisition_records.467.174-T-0100.jsonl",
    "start_record_line": 1550,
    "end_record_line": 1551,
    "source_file": "0100_acq.LOG"
  }
}
```

## Diagnostics

Permissive mode may write `timeline_diagnostics.jsonl` next to interval output
files for an input records directory. The file is a flat JSONL stream with one
diagnostic object per line and no top-level document wrapper. It is only written
when diagnostics are emitted.

The build pipeline emits this file when `--validation permissive` encounters
recoverable validation conditions such as duplicate or orphan acquisition
transitions. In `--validation strict`, the same conditions fail the command
instead of producing interval output for that directory.

Diagnostic shape:

```json
{
  "severity": "warning",
  "code": "orphan_stop_transition",
  "message": "stopped transition encountered with no active interval",
  "records_file": "log_acquisition_records.467.174-T-0100.jsonl",
  "record_line": 1,
  "issue_time": "2023-11-20T10:00:00.000000Z",
  "instrument_id": "T0100",
  "source_file": "0100_acq.LOG"
}
```

Fields:

- `severity`: currently `warning` or `error`.
- `code`: stable diagnostic code for the validation condition.
- `message`: human-readable diagnostic detail.
- `records_file`: normalized input JSONL filename that produced the diagnostic.
- `record_line`: 1-based input JSONL line number, or `null` if unavailable.
- `issue_time`: purported event time for the row that produced the diagnostic,
  or `null` if unavailable. BUF transition warnings use normalized UTC
  `record_time`; other diagnostics use the source row's `record_time` or `date`
  value when present.
- `instrument_id`: canonical source instrument/station ID, or `null` if unavailable.
- `source_file`: upstream source basename, or `null` if unavailable.

### BUF State Machine

Rows are grouped by `instrument_id` and processed chronologically by
`record_time`, preserving input order for tied timestamps.

Rules:

- `started` + `transition`: opens a new active interval.
- `started` + `assertion`: opens a conservative active interval only if no
  interval is already active.
- `stopped` + `transition`: closes the active interval with a closed end.
- `stopped` + `assertion`: if an interval is active, emits it with
  `end_time = null` and `end_boundary = "open_unknown"` because the true stop
  happened before the assertion.
- Repeated `stopped` assertions do not create intervals.
- Duplicate or orphan transitions are strict validation errors and permissive
  mode diagnostics.
- If input ends while an interval is active, the interval is emitted with
  `end_time = null` and `end_boundary = "open_unknown"`.

## DET / REQ Intervals

Input: `mer_event_records.<instrument_serial>.jsonl`

Legacy unsuffixed `mer_event_records.jsonl` inputs are also accepted when the
suffixed v2 file is not present.

DET classification:

- `criterion`, `snr`, `trig`, and `detrig` are all non-null.

REQ classification:

- `criterion`, `snr`, `trig`, and `detrig` are all null.

Mixed combinations emit diagnostics in permissive mode and fail validation in
strict mode.

Timing convention:

- `start_time = date`
- `end_time = date + (length - 1) / sampling_rate`

Output shape:

```json
{
  "schema_version": "0.2.0",
  "generated_by": {
    "package": "mermaid-timeline",
    "version": "0.1.1"
  },
  "instrument_id": "T0007",
  "interval_type": "det",
  "start_time": "2018-07-12T06:49:56.429681Z",
  "end_time": "2018-07-12T06:53:38.779681Z",
  "duration": 222.350000,
  "start_boundary": "closed",
  "end_boundary": "closed",
  "sampling_rate_hz": 20.0,
  "sample_count": 4448,
  "provenance": {
    "records_file": "mer_event_records.467.174-T-0100.jsonl",
    "record_line": 123,
    "source_file": "0007_XXXXXXXX.MER"
  }
}
```
