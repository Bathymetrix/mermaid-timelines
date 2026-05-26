# mermaid-timeline

`mermaid-timeline` consumes normalized `mermaid-records` JSONL outputs and
synthesizes interval-level timeline products.

The package is intentionally parse/coverage focused. It does not decode or
analyze waveform payloads. Future event-request and GCMT tooling can consume
these interval products alongside catalogs and travel-time products.

Requires Python 3.12 or newer.

Python import paths are not yet a stable public API. The stable v0.1 contract
is the `mermaid-timeline` CLI plus the documented JSONL input/output schemas.

## Inputs

- `log_acquisition_records.<instrument_serial>.jsonl` produces `buf` intervals.
- `mer_event_records.<instrument_serial>.jsonl` produces `det` and `req`
  intervals.

Legacy unsuffixed `log_acquisition_records.jsonl` and
`mer_event_records.jsonl` inputs are still accepted when the suffixed v2 files
are not present. When both forms exist, the suffixed v2 files are used.

## Outputs

Each output is a flat JSONL stream with one interval object per line:

- `buffer_intervals.jsonl`
- `detreq_intervals.jsonl`

## CLI

```bash
mermaid-timeline build \
  --input /path/to/mermaid-records/output \
  --validation strict
```

When `--output` is omitted, JSONL products are written back under the input
tree beside the normalized records. Pass `--output /path/to/timeline/output` to
write a separate mirrored output tree.

Validation modes:

- `strict`: raise on invalid or ambiguous input.
- `diagnostic`: emit diagnostics and continue where an interval can still be
  synthesized conservatively.

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

Then create self-contained Plotly availability reports. When `--input` is a
timeline output root, `plot` searches one level deep for instrument serial
subdirectories such as `467.174-T-0100`, then writes one HTML report beside each
subdirectory's interval JSONL files:

```bash
mermaid-timeline plot \
  --input /path/to/timeline/output
```

You can also pass one instrument serial directory directly:

```bash
mermaid-timeline plot \
  --input /path/to/timeline/output/467.174-T-0100 \
  --output /path/to/reports/T0100_data_intervals.html
```

In all-stations mode, use `--output /path/to/reports` to place per-instrument
reports in a single directory. Per-instrument filenames are generated as
`<instrument_id>_data_intervals.html`, where `instrument_id` is the canonical
5-character station name, such as `T0100`.

Use `--combined` to merge all float timelines into single report:

```bash
mermaid-timeline plot \
  --input /path/to/timeline/output \
  --combined \
  --output timeline.html
```

In combined mode, `--output` is an HTML file path. If it omits a suffix,
`.html` is appended. If `--output` is omitted, the report is written to
`timeline.html` under the input directory.

Reports distinguish `buf`, `det`, and `req` intervals, and mark `open_unknown`
ends as open-ended in the visual styling and hover text. Plotting scans the
input directory's immediate instrument serial subdirectories, or the input
directory itself when it is an instrument serial directory, for
`buffer_intervals.jsonl` and `detreq_intervals.jsonl`. Hover text includes the
source timeline subdirectory plus the inferred float serial when outputs use the
usual `467.174-T-0100` directory naming pattern.

Optional filters:

```bash
mermaid-timeline plot \
  --input /path/to/timeline/output \
  --instrument-id T0100 \
  --start-time 2023-01-01T00:00:00Z \
  --end-time 2024-01-01T00:00:00Z
```

`--instrument-id` accepts the canonical 5-character station name and resolves it
to one matching serial subdirectory. To select by exact subdirectory name, use
`--instrument-serial 467.174-T-0100`. If `--output` is a file path for a single
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
