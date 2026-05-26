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
_PLOT_LANES = {
    "det": {"axis": "y", "title": "DET", "domain": [2 / 3, 1]},
    "req": {"axis": "y2", "title": "REQ", "domain": [1 / 3, 2 / 3]},
    "buf": {"axis": "y3", "title": "BUFFER", "domain": [0, 1 / 3]},
}


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
) -> int:
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
    _write_availability_html(
        intervals,
        _ensure_html_suffix(output),
        go=go,
        offline_plot=offline_plot,
    )
    return len(intervals)


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
                output=report_path,
            )
        )

    return reports


def _parse_filter_instrument_id(instrument_id: str | None) -> str | None:
    if instrument_id is None:
        return None
    stripped = instrument_id.strip()
    if len(stripped) != 5:
        raise ValueError(
            "--instrument-id must be a 5-character station name such as T0100"
        )
    return stripped


def _parse_filter_instrument_serial(instrument_serial: str | None) -> str | None:
    if instrument_serial is None:
        return None
    stripped = instrument_serial.strip()
    try:
        parse_instrument_name(stripped)
    except ValueError as exc:
        raise ValueError(
            "--instrument-serial must be a canonical serial such as "
            "467.174-T-0100"
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
                f"--instrument-serial {filters.instrument_serial!r} did not match "
                f"a subdirectory under {root}"
            )
        if len(matches) > 1:
            names = ", ".join(str(match.path.relative_to(root)) for match in matches)
            raise ValueError(
                f"--instrument-serial {filters.instrument_serial!r} matched "
                f"multiple subdirectories: {names}"
            )
        return tuple(matches)

    if filters.instrument_id is not None:
        matches = _serial_directories_for_instrument_id(root, filters.instrument_id)
        if not matches:
            raise ValueError(
                f"--instrument-id {filters.instrument_id!r} did not match any "
                f"serial subdirectory of {root}"
            )
        if len(matches) > 1:
            names = ", ".join(match.path.name for match in matches)
            raise ValueError(
                f"--instrument-id {filters.instrument_id!r} matched multiple "
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
            f"--instrument-serial {filters.instrument_serial!r} does not match "
            f"input serial directory {instrument_name.serial!r}"
        )
    if (
        filters.instrument_id is not None
        and filters.instrument_id != instrument_name.instrument_id
    ):
        raise ValueError(
            f"--instrument-id {filters.instrument_id!r} does not match "
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
    figure = go.Figure()

    for interval in intervals:
        is_open = interval.end_boundary == "open_unknown"
        display_end = interval.end_time if interval.end_time is not None else horizon
        if display_end <= interval.start_time:
            display_end = interval.start_time + timedelta(hours=1)
        hover = _hover_text(interval)
        color = colors.get(interval.interval_type, "#4A5568")
        lane = _PLOT_LANES.get(interval.interval_type, _PLOT_LANES["buf"])
        dash = "dash" if is_open else "solid"
        opacity = 0.45 if is_open else 0.95
        marker = {
            "size": 10,
            "symbol": "triangle-right" if is_open else "line-ew",
            "color": color,
        }
        figure.add_trace(
            go.Scatter(
                x=[interval.start_time, display_end],
                y=[interval.instrument_id, interval.instrument_id],
                mode="lines+markers" if is_open else "lines",
                line={"color": color, "width": 12, "dash": dash},
                marker=marker,
                opacity=opacity,
                name=interval.interval_type,
                yaxis=lane["axis"],
                legendgroup=interval.interval_type,
                showlegend=_first_trace_for_type(figure, interval.interval_type),
                hoverinfo="text",
                text=[hover, hover],
            )
        )

    figure.update_layout(
        title="MERMAID Timeline Availability",
        xaxis_title="Time",
        yaxis={
            "title": _PLOT_LANES["det"]["title"],
            "domain": _PLOT_LANES["det"]["domain"],
            "type": "category",
            "autorange": "reversed",
        },
        yaxis2={
            "title": _PLOT_LANES["req"]["title"],
            "domain": _PLOT_LANES["req"]["domain"],
            "type": "category",
            "autorange": "reversed",
        },
        yaxis3={
            "title": _PLOT_LANES["buf"]["title"],
            "domain": _PLOT_LANES["buf"]["domain"],
            "type": "category",
            "autorange": "reversed",
        },
        hovermode="closest",
        template="plotly_white",
        margin={"l": 90, "r": 40, "t": 70, "b": 60},
        legend_title_text="Interval type",
    )
    return figure


def _first_trace_for_type(figure: object, interval_type: str) -> bool:
    return all(trace.name != interval_type for trace in figure.data)


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


def _hover_text(interval: IntervalRow) -> str:
    provenance = interval.provenance
    lines = [
        f"instrument_id: {interval.instrument_id}",
        f"interval_type: {interval.interval_type}",
        f"start_time: {interval.start_time_text}",
        f"end_time: {interval.end_time_text}",
        f"duration: {_duration_text(interval.duration)}",
        f"start_boundary: {interval.start_boundary}",
        f"end_boundary: {interval.end_boundary}",
    ]
    if interval.float_serial is not None:
        lines.append(f"float_serial: {interval.float_serial}")
    if interval.timeline_subdir is not None:
        lines.append(f"timeline_subdir: {interval.timeline_subdir}")
    if interval.end_boundary == "open_unknown":
        lines.append("status: open-ended; true end unknown")
    for key in (
        "source_file",
        "records_file",
        "record_line",
        "start_record_line",
        "end_record_line",
    ):
        value = provenance.get(key)
        if value is not None:
            lines.append(f"{key}: {value}")
    return "<br>".join(lines)


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
