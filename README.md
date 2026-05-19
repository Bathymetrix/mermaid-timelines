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

- `log_acquisition_records.jsonl` produces `buf` intervals.
- `mer_event_records.jsonl` produces `det` and `req` intervals.

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
contract.

Install the reporting extra when you want HTML plots:

```bash
pip install "mermaid-timeline[plot]"
```

Then create self-contained Plotly availability reports. By default, `plot`
writes one HTML report per `instrument_id` beside the input interval JSONL files:

```bash
mermaid-timeline plot \
  --input /path/to/timeline/output
```

Use `--output /path/to/reports` to place per-instrument reports in a single
directory. Per-instrument filenames are generated as
`timeline-<instrument_id>.html`.

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
ends as open-ended in the visual styling and hover text. Plotting recursively
scans the input directory for
`buffer_intervals.jsonl` and `detreq_intervals.jsonl`, and hover text includes
the source timeline subdirectory plus the inferred float serial when outputs use
the usual `467.174-T-0100` directory naming pattern.

Optional filters:

```bash
mermaid-timeline plot \
  --input /path/to/timeline/output \
  --instrument-id 0100 \
  --start-time 2023-01-01T00:00:00Z \
  --end-time 2024-01-01T00:00:00Z
```

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
