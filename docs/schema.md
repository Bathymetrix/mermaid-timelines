# mermaid-timeline Schema

Schema version: `0.1.0`

All products are JSONL streams. There is no top-level document wrapper.

## Common Fields

Every interval record includes:

- `schema_version`
- `generated_by`
- `instrument_id`
- `interval_type`
- `start_time`
- `end_time`
- `start_boundary`
- `end_boundary`
- `provenance`

Boundary vocabulary for `0.1.0`:

- `closed`: the interval boundary timestamp is included in the known interval.
- `open_unknown`: the true boundary is unknown and must not be inferred from the
  evidence timestamp.

`interval_type` vocabulary for `0.1.0`:

- `buf`: acquisition buffer interval synthesized from acquisition records.
- `det`: detected MER event interval.
- `req`: requested MER event interval without detection fields.

`provenance` is intentionally small and points back to the normalized JSONL row
or rows used to synthesize the interval. BUF intervals include
`records_file`, `start_record_line`, `end_record_line`, and `source_file`.
DET/REQ intervals include `records_file`, `record_line`, and `source_file`.

## BUF Intervals

Input: `log_acquisition_records.jsonl`

Required input fields:

- `instrument_id`
- `record_time`
- `acquisition_state`
- `acquisition_evidence_kind`

Output shape:

```json
{
  "schema_version": "0.1.0",
  "generated_by": {
    "package": "mermaid-timeline",
    "version": "0.1.0"
  },
  "instrument_id": "0100",
  "interval_type": "buf",
  "start_time": "2023-11-20T10:00:00Z",
  "end_time": null,
  "start_boundary": "closed",
  "end_boundary": "open_unknown",
  "start_evidence_kind": "transition",
  "end_evidence_kind": "assertion",
  "start_evidence_time": "2023-11-20T10:00:00Z",
  "end_evidence_time": "2023-11-20T12:45:10Z",
  "provenance": {
    "records_file": "log_acquisition_records.jsonl",
    "start_record_line": 1550,
    "end_record_line": 1551,
    "source_file": "0100_acq.LOG"
  }
}
```

## Diagnostics

Diagnostic mode may write `timeline_diagnostics.jsonl` next to interval output
files for an input records directory. The file is a flat JSONL stream with one
diagnostic object per line and no top-level document wrapper. It is only written
when diagnostics are emitted.

The build pipeline emits this file when `--validation diagnostic` encounters
recoverable validation conditions such as duplicate or orphan acquisition
transitions. In `--validation strict`, the same conditions fail the command
instead of producing interval output for that directory.

Diagnostic shape:

```json
{
  "severity": "warning",
  "code": "orphan_stop_transition",
  "message": "stopped transition encountered with no active interval",
  "records_file": "log_acquisition_records.jsonl",
  "record_line": 1,
  "instrument_id": "0100",
  "source_file": "0100_acq.LOG"
}
```

Fields:

- `severity`: currently `warning` or `error`.
- `code`: stable diagnostic code for the validation condition.
- `message`: human-readable diagnostic detail.
- `records_file`: normalized input JSONL filename that produced the diagnostic.
- `record_line`: 1-based input JSONL line number, or `null` if unavailable.
- `instrument_id`: source instrument ID, or `null` if unavailable.
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
- Duplicate or orphan transitions are strict validation errors and diagnostic
  mode diagnostics.
- If input ends while an interval is active, the interval is emitted with
  `end_time = null` and `end_boundary = "open_unknown"`.

## DET / REQ Intervals

Input: `mer_event_records.jsonl`

DET classification:

- `criterion`, `snr`, `trig`, and `detrig` are all non-null.

REQ classification:

- `criterion`, `snr`, `trig`, and `detrig` are all null.

Mixed combinations are validation failures.

Timing convention:

- `start_time = date`
- `end_time = date + (length - 1) / sampling_rate`

Output shape:

```json
{
  "schema_version": "0.1.0",
  "generated_by": {
    "package": "mermaid-timeline",
    "version": "0.1.0"
  },
  "instrument_id": "0007",
  "interval_type": "det",
  "start_time": "2018-07-12T06:49:56.429681Z",
  "end_time": "2018-07-12T06:53:38.779681Z",
  "start_boundary": "closed",
  "end_boundary": "closed",
  "sampling_rate_hz": 20.0,
  "sample_count": 4448,
  "provenance": {
    "records_file": "mer_event_records.jsonl",
    "record_line": 123,
    "source_file": "0007_XXXXXXXX.MER"
  }
}
```
