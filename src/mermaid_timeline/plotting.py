"""Optional Plotly HTML availability report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

from mermaid_timeline._time import parse_timestamp
from mermaid_timeline.instrument_name import (
    InstrumentName,
    maybe_parse_instrument_name,
    parse_instrument_name,
)
from mermaid_timeline.interval_reader import IntervalRow, read_interval_rows
from mermaid_timeline.pipeline import BUFFER_INTERVALS_FILE, DETREQ_INTERVALS_FILE

_HTML_SUFFIXES = {".htm", ".html"}
_DRAW_ORDER = {"buf": 0, "req": 1, "det": 2}
_LEGEND_ORDER = {"det": 0, "req": 1, "buf": 2}
_LANE_OFFSETS = {"det": -0.06, "req": -0.06, "buf": 0.06}
_LANE_HEIGHT = 0.12


class MissingPlotlyError(RuntimeError):
    """Raised when the optional Plotly dependency is unavailable."""


@dataclass(frozen=True, slots=True)
class PlotFilters:
    instrument_id: str | None = None
    instrument_serial: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class _IntervalDirectory:
    path: Path
    instrument_name: InstrumentName | None


@dataclass(frozen=True, slots=True)
class _PlotReport:
    instrument_id: str
    interval_count: int
    interval_count_by_type: dict[str, int]
    duration_seconds_by_type: dict[str, float]
    output: Path


def parse_plot_filters(
    *,
    instrument_id: str | None = None,
    instrument_serial: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> PlotFilters:
    parsed_instrument_id = _parse_filter_instrument_id(instrument_id)
    parsed_instrument_serial = _parse_filter_instrument_serial(instrument_serial)
    return PlotFilters(
        instrument_id=parsed_instrument_id,
        instrument_serial=parsed_instrument_serial,
        start_time=(
            parse_timestamp(start_time, field_name="start_time")
            if start_time is not None
            else None
        ),
        end_time=(
            parse_timestamp(end_time, field_name="end_time")
            if end_time is not None
            else None
        ),
    )


def write_availability_html(
    input_root: Path,
    output: Path,
    *,
    filters: PlotFilters | None = None,
) -> _PlotReport:
    """Write a self-contained Plotly HTML availability report."""

    filters = filters or PlotFilters()
    root = input_root.resolve()
    interval_dirs = _plot_interval_directories(root, filters)
    intervals = _filter_intervals(
        read_interval_rows(
            root,
            interval_dirs=[directory.path for directory in interval_dirs],
        ),
        filters,
    )
    go, offline_plot = _load_plotly()
    output = _ensure_html_suffix(output)
    _write_availability_html(
        intervals,
        output,
        go=go,
        offline_plot=offline_plot,
    )
    return _PlotReport(
        instrument_id="combined",
        interval_count=len(intervals),
        interval_count_by_type=_interval_count_by_type(intervals),
        duration_seconds_by_type=_duration_seconds_by_type(intervals),
        output=output,
    )


def _write_instrument_availability_html(
    input_root: Path,
    output: Path | None = None,
    *,
    filters: PlotFilters | None = None,
) -> list[_PlotReport]:
    """Write one self-contained Plotly HTML availability report per instrument."""

    filters = filters or PlotFilters()
    root = input_root.resolve()
    interval_dirs = _plot_interval_directories(root, filters)
    output_file = _single_instrument_output_file(
        output,
        single_station_output=_uses_explicit_instrument_selector(filters),
    )
    if output_file is not None and len(interval_dirs) != 1:
        raise ValueError(
            "--output may be an HTML file only when one instrument is selected; "
            "pass a directory or use --combined"
        )

    go, offline_plot = _load_plotly()
    reports: list[_PlotReport] = []
    used_outputs: set[Path] = set()
    for interval_dir in interval_dirs:
        instrument_intervals = _filter_intervals(
            read_interval_rows(root, interval_dirs=[interval_dir.path]),
            filters,
        )
        if not instrument_intervals:
            continue
        instrument_id = _report_instrument_id(interval_dir, instrument_intervals)
        if output_file is not None:
            report_path = output_file
        else:
            output_dir = _plot_report_output_dir(root, interval_dir, output)
            report_path = output_dir / _instrument_report_filename(instrument_id)

        report_path = _ensure_html_suffix(report_path)
        resolved_report_path = report_path.resolve()
        if resolved_report_path in used_outputs:
            raise ValueError(f"multiple instruments resolve to output {report_path}")
        used_outputs.add(resolved_report_path)
        _write_availability_html(
            instrument_intervals,
            report_path,
            go=go,
            offline_plot=offline_plot,
        )
        reports.append(
            _PlotReport(
                instrument_id=instrument_id,
                interval_count=len(instrument_intervals),
                interval_count_by_type=_interval_count_by_type(
                    instrument_intervals
                ),
                duration_seconds_by_type=_duration_seconds_by_type(
                    instrument_intervals
                ),
                output=report_path,
            )
        )

    return reports


def _parse_filter_instrument_id(instrument_id: str | None) -> str | None:
    if instrument_id is None:
        return None
    stripped = instrument_id.strip()
    if len(stripped) != 5:
        raise ValueError("--id must be a 5-character station name such as T0100")
    return stripped


def _parse_filter_instrument_serial(instrument_serial: str | None) -> str | None:
    if instrument_serial is None:
        return None
    stripped = instrument_serial.strip()
    try:
        parse_instrument_name(stripped)
    except ValueError as exc:
        raise ValueError(
            "--ser must be a canonical serial such as 467.174-T-0100"
        ) from exc
    return stripped


def _ensure_html_suffix(path: Path) -> Path:
    if path.suffix.lower() in _HTML_SUFFIXES:
        return path
    if path.suffix:
        return path.with_name(f"{path.name}.html")
    return path.with_suffix(".html")


def _write_availability_html(
    intervals: Sequence[IntervalRow],
    output: Path,
    *,
    go: object,
    offline_plot: object,
) -> None:
    figure = _build_figure(intervals, go)
    output.parent.mkdir(parents=True, exist_ok=True)
    html = offline_plot(
        figure,
        include_plotlyjs=True,
        output_type="div",
        auto_open=False,
    )
    output.write_text(_html_document(html), encoding="utf-8")


def _load_plotly() -> tuple[object, object]:
    try:
        import plotly.graph_objects as go
        from plotly.offline import plot
    except ModuleNotFoundError as exc:
        raise MissingPlotlyError(
            "Plotly is required for 'mermaid-timeline plot'. "
            "Install with: pip install 'mermaid-timeline[plot]'"
        ) from exc
    return go, plot


def _plot_interval_directories(
    input_root: Path,
    filters: PlotFilters,
) -> tuple[_IntervalDirectory, ...]:
    root = input_root.resolve()
    if not root.is_dir():
        raise ValueError(f"--input must be a directory: {root}")

    root_instrument_name = maybe_parse_instrument_name(root.name)
    if root_instrument_name is not None and _has_interval_product(root):
        directory = _IntervalDirectory(root, root_instrument_name)
        _validate_single_serial_input(directory, filters)
        return (directory,)

    if filters.instrument_serial is not None:
        matches = _serial_directories_for_instrument_serial(
            root,
            filters.instrument_serial,
        )
        if not matches:
            raise ValueError(
                f"--ser {filters.instrument_serial!r} did not match "
                f"a subdirectory under {root}"
            )
        if len(matches) > 1:
            names = ", ".join(str(match.path.relative_to(root)) for match in matches)
            raise ValueError(
                f"--ser {filters.instrument_serial!r} matched "
                f"multiple subdirectories: {names}"
            )
        return tuple(matches)

    if filters.instrument_id is not None:
        matches = _serial_directories_for_instrument_id(root, filters.instrument_id)
        if not matches:
            raise ValueError(
                f"--id {filters.instrument_id!r} did not match any "
                f"serial subdirectory of {root}"
            )
        if len(matches) > 1:
            names = ", ".join(match.path.name for match in matches)
            raise ValueError(
                f"--id {filters.instrument_id!r} matched multiple "
                f"serial subdirectories: {names}"
            )
        return tuple(matches)

    interval_dirs = tuple(
        _IntervalDirectory(path.resolve(), maybe_parse_instrument_name(path.name))
        for path in _recursive_child_dirs(root)
        if _has_interval_product(path)
    )
    if not interval_dirs:
        raise ValueError(
            f"no interval JSONL files found under {root}; pass a timeline output "
            "root containing instrument serial subdirectories, or pass one "
            "instrument serial directory directly"
        )
    return interval_dirs


def _validate_single_serial_input(
    interval_dir: _IntervalDirectory,
    filters: PlotFilters,
) -> None:
    instrument_name = interval_dir.instrument_name
    if instrument_name is None:
        return
    if (
        filters.instrument_serial is not None
        and filters.instrument_serial != instrument_name.serial
    ):
        raise ValueError(
            f"--ser {filters.instrument_serial!r} does not match "
            f"input serial directory {instrument_name.serial!r}"
        )
    if (
        filters.instrument_id is not None
        and filters.instrument_id != instrument_name.instrument_id
    ):
        raise ValueError(
            f"--id {filters.instrument_id!r} does not match "
            f"input serial directory instrument ID {instrument_name.instrument_id!r}"
        )


def _serial_directories_for_instrument_id(
    root: Path,
    instrument_id: str,
) -> list[_IntervalDirectory]:
    matches: list[_IntervalDirectory] = []
    for path in _recursive_child_dirs(root):
        instrument_name = maybe_parse_instrument_name(path.name)
        if instrument_name is None:
            continue
        if not _has_interval_product(path):
            continue
        if instrument_name.instrument_id == instrument_id:
            matches.append(_IntervalDirectory(path.resolve(), instrument_name))
    return matches


def _serial_directories_for_instrument_serial(
    root: Path,
    instrument_serial: str,
) -> list[_IntervalDirectory]:
    instrument_name = parse_instrument_name(instrument_serial)
    return [
        _IntervalDirectory(path.resolve(), instrument_name)
        for path in _recursive_child_dirs(root)
        if path.name == instrument_serial and _has_interval_product(path)
    ]


def _recursive_child_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_dir())


def _plot_report_output_dir(
    root: Path,
    interval_dir: _IntervalDirectory,
    output: Path | None,
) -> Path:
    if output is None:
        return interval_dir.path
    return output / interval_dir.path.relative_to(root)


def _has_interval_product(path: Path) -> bool:
    return any(
        (path / filename).is_file()
        for filename in (BUFFER_INTERVALS_FILE, DETREQ_INTERVALS_FILE)
    )


def _filter_intervals(
    intervals: Iterable[IntervalRow],
    filters: PlotFilters,
) -> list[IntervalRow]:
    selected: list[IntervalRow] = []
    for interval in intervals:
        if filters.start_time is not None:
            if interval.end_time is not None and interval.end_time < filters.start_time:
                continue
        if filters.end_time is not None and interval.start_time > filters.end_time:
            continue
        selected.append(interval)
    return selected


def _interval_count_by_type(intervals: Sequence[IntervalRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for interval in intervals:
        counts[interval.interval_type] = counts.get(interval.interval_type, 0) + 1
    return counts


def _duration_seconds_by_type(intervals: Sequence[IntervalRow]) -> dict[str, float]:
    durations: dict[str, float] = {}
    for interval in intervals:
        if interval.duration is None:
            continue
        durations[interval.interval_type] = (
            durations.get(interval.interval_type, 0.0) + interval.duration
        )
    return durations


def _single_instrument_output_file(
    output: Path | None,
    *,
    single_station_output: bool,
) -> Path | None:
    if output is None:
        return None
    if output.exists() and output.is_dir():
        return None
    if output.suffix or single_station_output:
        return _ensure_html_suffix(output)
    return None


def _uses_explicit_instrument_selector(filters: PlotFilters) -> bool:
    return filters.instrument_id is not None or filters.instrument_serial is not None


def _report_instrument_id(
    interval_dir: _IntervalDirectory,
    intervals: Sequence[IntervalRow],
) -> str:
    if interval_dir.instrument_name is not None:
        return interval_dir.instrument_name.instrument_id
    interval_ids = sorted({interval.instrument_id for interval in intervals})
    if len(interval_ids) == 1:
        return interval_ids[0]
    return interval_dir.path.name


def _instrument_report_filename(instrument_id: str) -> str:
    safe_id = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in instrument_id.strip()
    )
    return f"{safe_id or 'unknown'}_data_intervals.html"


def _build_figure(intervals: Sequence[IntervalRow], go: object) -> object:
    colors = {
        "buf": "#000000",
        "det": "#1F77B4",
        "req": "#D627B0",
    }
    horizon = _plot_horizon(intervals)
    y_centers = _instrument_y_centers(intervals)
    figure = go.Figure()

    for interval in _plot_draw_order(intervals):
        is_open = interval.end_boundary == "open_unknown"
        display_end = interval.end_time if interval.end_time is not None else horizon
        if display_end <= interval.start_time:
            display_end = interval.start_time + timedelta(hours=1)
        customdata, hovertemplate = _hover_data(interval)
        color = colors.get(interval.interval_type, "#4A5568")
        opacity = 0.45 if is_open else 0.95
        figure.add_trace(
            go.Bar(
                orientation="h",
                base=[interval.start_time],
                x=[_duration_milliseconds(interval.start_time, display_end)],
                y=[_interval_lane_y(interval, y_centers)],
                width=_LANE_HEIGHT,
                marker={
                    "color": color,
                    "line": {
                        "color": color,
                        "width": 1,
                    },
                },
                opacity=opacity,
                name=interval.interval_type,
                legendgroup=interval.interval_type,
                legendrank=_LEGEND_ORDER.get(interval.interval_type, 99),
                showlegend=_first_trace_for_type(figure, interval.interval_type),
                customdata=[customdata],
                hovertemplate=hovertemplate,
            )
        )

    figure.update_layout(
        title="MERMAID Timeline Availability",
        xaxis={
            "title": "Time",
            "type": "date",
        },
        yaxis={
            "title": "Instrument ID",
            "type": "linear",
            "range": _yaxis_range(y_centers),
            "tickmode": "array",
            "tickvals": list(y_centers.values()),
            "ticktext": list(y_centers.keys()),
        },
        hovermode="closest",
        barmode="overlay",
        template="plotly_white",
        margin={"l": 90, "r": 40, "t": 70, "b": 60},
        legend_title_text="Interval type",
    )
    return figure


def _plot_draw_order(intervals: Sequence[IntervalRow]) -> list[IntervalRow]:
    return [
        interval
        for _, interval in sorted(
            enumerate(intervals),
            key=lambda item: (_DRAW_ORDER.get(item[1].interval_type, 99), item[0]),
        )
    ]


def _first_trace_for_type(figure: object, interval_type: str) -> bool:
    return all(trace.name != interval_type for trace in figure.data)


def _instrument_y_centers(intervals: Sequence[IntervalRow]) -> dict[str, float]:
    instrument_ids = sorted({interval.instrument_id for interval in intervals})
    return {
        instrument_id: float(index)
        for index, instrument_id in enumerate(instrument_ids)
    }


def _interval_lane_y(
    interval: IntervalRow,
    y_centers: dict[str, float],
) -> float:
    return y_centers[interval.instrument_id] + _LANE_OFFSETS.get(
        interval.interval_type,
        0.0,
    )


def _yaxis_range(y_centers: dict[str, float]) -> list[float]:
    if not y_centers:
        return [0.5, -0.5]
    centers = list(y_centers.values())
    return [max(centers) + 0.5, min(centers) - 0.5]


def _plot_horizon(intervals: Sequence[IntervalRow]) -> datetime:
    times: list[datetime] = []
    for interval in intervals:
        times.append(interval.start_time)
        if interval.end_time is not None:
            times.append(interval.end_time)
    if not times:
        return datetime.now().astimezone()
    start = min(times)
    end = max(times)
    if end <= start:
        return start + timedelta(hours=1)
    return end


def _duration_milliseconds(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() * 1000.0


def _hover_data(interval: IntervalRow) -> tuple[list[str], str]:
    lines = _hover_lines(interval)
    customdata = [value for _, value in lines]
    template_lines = [
        f"{label}: %{{customdata[{index}]}}"
        for index, (label, _) in enumerate(lines)
    ]
    return customdata, "<br>".join(template_lines) + "<extra></extra>"


def _hover_lines(interval: IntervalRow) -> list[tuple[str, str]]:
    provenance = interval.provenance
    lines = [
        ("interval_type", interval.interval_type),
        ("instrument_id", interval.instrument_id),
        ("start_time", interval.start_time_text),
        ("end_time", _optional_text(interval.end_time_text)),
        ("duration_seconds", _duration_text(interval.duration)),
        ("start_boundary", interval.start_boundary),
        ("end_boundary", interval.end_boundary),
    ]
    if interval.float_serial is not None:
        lines.append(("float_serial", interval.float_serial))
    if interval.timeline_subdir is not None:
        lines.append(("timeline_subdir", interval.timeline_subdir))
    if interval.end_boundary == "open_unknown":
        lines.append(("status", "open-ended; true end unknown"))
    for key in _metadata_hover_keys(interval.interval_type):
        value = interval.metadata.get(key)
        if value is not None:
            lines.append((key, str(value)))
    for key in (
        "source_file",
        "records_file",
        "record_line",
        "start_record_line",
        "end_record_line",
    ):
        value = provenance.get(key)
        if value is not None:
            lines.append((key, str(value)))
    return lines


def _metadata_hover_keys(interval_type: str) -> tuple[str, ...]:
    if interval_type == "buf":
        return (
            "start_evidence_kind",
            "end_evidence_kind",
            "start_evidence_time",
            "end_evidence_time",
        )
    if interval_type in {"det", "req"}:
        return (
            "criterion",
            "snr",
            "trig",
            "detrig",
            "sampling_rate_hz",
            "sample_count",
            "filename",
            "frequency",
            "request",
        )
    return ()


def _optional_text(value: object | None) -> str:
    if value is None:
        return "null"
    return str(value)


def _duration_text(duration: float | None) -> str:
    if duration is None:
        return "null"
    return f"{duration:.6f}"


def _html_document(plot_div: str) -> str:
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            "  <title>MERMAID Timeline Availability</title>",
            "</head>",
            "<body>",
            plot_div,
            "</body>",
            "</html>",
            "",
        ]
    )
