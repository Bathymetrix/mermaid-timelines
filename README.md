# mermaid-timelines

`mermaid-timeline` consumes normalized `mermaid-records` JSONL outputs and
synthesizes interval-level timeline products.

The package is intentionally parse/coverage focused. It does not decode or
analyze waveform payloads. Future event-request and GCMT tooling can consume
these interval products alongside catalogs and travel-time products.

Requires Python 3.12 or newer; Python 3.12 through 3.14 are supported.

Python import paths are not yet a stable public API. The stable v0.2 contract
is the `mermaid-timeline` CLI plus the documented JSONL input/output schemas.

## Inputs

- `log_acquisition_records.<instrument_serial>.jsonl` produces `buf` intervals.
- `mer_event_records.<instrument_serial>.jsonl` produces `det` and `req`
  intervals.

Legacy unsuffixed `log_acquisition_records.jsonl` and
`mer_event_records.jsonl` inputs are still accepted when the suffixed v2 files
are not present. When both forms exist, the suffixed v2 files are used.

## Outputs

Each output is a flat JSONL stream:

- `buffer_intervals.jsonl`
- `detreq_intervals.jsonl`
- `summary_intervals.jsonl`

`buffer_intervals.jsonl` and `detreq_intervals.jsonl` include a `duration`
field immediately after `end_time`. Closed intervals emit known durations in
seconds as JSON numbers with exactly 6 decimal places. Open-ended BUF intervals
emit `duration: null`.

`summary_intervals.jsonl` aggregates known BUF/DET/REQ interval durations into
UTC day, ISO Monday-start week, month, and year bins. Intervals are clipped to
half-open bin boundaries, and BUF, DET, and REQ totals remain separate. Overlaps
within the same interval type are summed rather than unioned. Summary duration
and fraction values are also emitted as JSON numbers with exactly 6 decimal
places.

## CLI

```bash
mermaid-timeline build
```

By default, `build` reads normalized records from `$MERMAID/records` and writes
JSONL products under `$MERMAID/timelines`, creating output directories as needed.
Pass `--input /path/to/records` or `--output /path/to/timelines` to override
either default.

Validation modes:

- `permissive` (default): emit diagnostics and continue where an interval can
  still be synthesized conservatively.
- `strict`: raise on invalid or ambiguous input.

## Optional Plotting

Plotting is an optional reporting layer over the synthesized interval JSONL
files. It is not part of interval synthesis and does not change the core JSONL
contract. Run `build` before `plot`; `plot` reads existing
`buffer_intervals.jsonl` and `detreq_intervals.jsonl` files and does not create
them.

Install the reporting extra when you want HTML plots:

```bash
pip install "mermaid-timeline[plot]"
```

Then create self-contained Plotly availability reports. By default, `plot` reads
timeline files from `$MERMAID/timelines` and writes reports under
`$MERMAID/timelines`. When `--input` is a timeline output root, `plot` searches
one level deep for instrument serial subdirectories such as `467.174-T-0100`,
then writes one HTML report for each instrument:

```bash
mermaid-timeline plot
```

You can also pass one instrument serial directory directly:

```bash
mermaid-timeline plot \
  --input /path/to/timelines/output/467.174-T-0100 \
  --output /path/to/reports/T0100_data_intervals.html
```

In all-stations mode, use `--output /path/to/reports` to place per-instrument
reports in a single directory. Per-instrument filenames are generated as
`<instrument_id>_data_intervals.html`, where `instrument_id` is the canonical
5-character station name, such as `T0100`.

Use `--combined` to merge all float timelines into single report:

```bash
mermaid-timeline plot \
  --combined \
  --output /path/to/reports/timeline.html
```

In combined mode, `--output` is an HTML file path. If it omits a suffix,
`.html` is appended. If `--output` is omitted, the report is written to
`timeline.html` under `$MERMAID/timelines`.

Reports distinguish `buf`, `det`, and `req` intervals, and mark `open_unknown`
ends as open-ended in the visual styling and hover text. Plotting scans the
input directory's immediate instrument serial subdirectories, or the input
directory itself when it is an instrument serial directory, for
`buffer_intervals.jsonl` and `detreq_intervals.jsonl`. Hover text includes
interval duration, the source timeline subdirectory, and the inferred float
serial when outputs use the usual `467.174-T-0100` directory naming pattern.

Optional filters:

```bash
mermaid-timeline plot \
  --input /path/to/timelines/output \
  --id T0100 \
  --start-time 2023-01-01T00:00:00Z \
  --end-time 2024-01-01T00:00:00Z
```

`--id` accepts the canonical 5-character station name and resolves it
to one matching serial subdirectory. To select by exact subdirectory name, use
`--ser 467.174-T-0100`. If `--output` is a file path for a single
selected station, `.html` is appended when needed.

## State-Machine Summary

Acquisition rows are interpreted from normalized fields only:

- `acquisition_state`
- `acquisition_evidence_kind`

Transitions change state. Assertions observe state. A `started` assertion can
open a conservative interval at the assertion time. A `stopped` assertion can
close knowledge of an active interval without fabricating an end timestamp, so
the interval end remains `null` with `end_boundary = "open_unknown"`.

See [docs/schema.md](docs/schema.md) for the pinned schema and state-machine
rules.
