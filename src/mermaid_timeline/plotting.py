"""Optional Plotly HTML availability report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

from mermaid_timeline._time import parse_timestamp
from mermaid_timeline.interval_reader import IntervalRow, read_interval_rows


class MissingPlotlyError(RuntimeError):
    """Raised when the optional Plotly dependency is unavailable."""


@dataclass(frozen=True, slots=True)
class PlotFilters:
    instrument_ids: tuple[str, ...] = ()
    start_time: datetime | None = None
    end_time: datetime | None = None


def parse_plot_filters(
    *,
    instrument_ids: Sequence[str] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> PlotFilters:
    return PlotFilters(
        instrument_ids=tuple(instrument_ids or ()),
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

    go, offline_plot = _load_plotly()
    filters = filters or PlotFilters()
    intervals = _filter_intervals(read_interval_rows(input_root), filters)
    figure = _build_figure(intervals, go)

    output.parent.mkdir(parents=True, exist_ok=True)
    html = offline_plot(
        figure,
        include_plotlyjs=True,
        output_type="div",
        auto_open=False,
    )
    output.write_text(_html_document(html), encoding="utf-8")
    return len(intervals)


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


def _filter_intervals(
    intervals: Iterable[IntervalRow],
    filters: PlotFilters,
) -> list[IntervalRow]:
    instrument_ids = set(filters.instrument_ids)
    selected: list[IntervalRow] = []
    for interval in intervals:
        if instrument_ids and interval.instrument_id not in instrument_ids:
            continue
        if filters.start_time is not None:
            if interval.end_time is not None and interval.end_time < filters.start_time:
                continue
        if filters.end_time is not None and interval.start_time > filters.end_time:
            continue
        selected.append(interval)
    return selected


def _build_figure(intervals: Sequence[IntervalRow], go: object) -> object:
    colors = {
        "buf": "#2B6CB0",
        "det": "#C05621",
        "req": "#2F855A",
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
                legendgroup=interval.interval_type,
                showlegend=_first_trace_for_type(figure, interval.interval_type),
                hoverinfo="text",
                text=[hover, hover],
            )
        )

    figure.update_layout(
        title="MERMAID Timeline Availability",
        xaxis_title="Time",
        yaxis_title="Instrument",
        hovermode="closest",
        template="plotly_white",
        margin={"l": 90, "r": 40, "t": 70, "b": 60},
        legend_title_text="Interval type",
    )
    figure.update_yaxes(type="category", autorange="reversed")
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
        f"start_boundary: {interval.start_boundary}",
        f"end_boundary: {interval.end_boundary}",
    ]
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
