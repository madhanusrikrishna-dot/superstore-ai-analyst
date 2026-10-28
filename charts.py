"""
charts.py - one chart style per question type, so the chart always fits the question:
  trend -> line, comparison -> bar, correlation -> bar of buckets / scatter,
  segmentation -> bar, cohort -> heatmap, forecast -> line with dashed future.
"""

import altair as alt
import pandas as pd

BLUE = "#4c9aff"
RED = "#e5534b"
GREEN = "#3fb950"
GREY = "#8b949e"
ORANGE = "#f0883e"


def _axis_format(metric: str) -> str:
    if metric in ("margin", "discount"):
        return ".0%"
    if metric in ("orders", "customers", "quantity"):
        return ",.0f"
    return "$,.0f"


def bar(df: pd.DataFrame, label: str, value: str, metric: str, title: str = "",
        highlight: str | None = None) -> alt.Chart:
    """Horizontal bars in the table's order; losses red; one highlighted bar."""
    data = df[[label, value]].copy()
    data[label] = data[label].astype(str)
    order = list(data[label])

    if highlight is not None:
        color = alt.condition(alt.datum[label] == str(highlight), alt.value(ORANGE), alt.value(BLUE))
    else:
        color = alt.condition(alt.datum[value] < 0, alt.value(RED), alt.value(BLUE))

    base = alt.Chart(data, title=title).encode(
        y=alt.Y(f"{label}:N", sort=order, title=None, axis=alt.Axis(labelLimit=220)),
        x=alt.X(f"{value}:Q", title=None, axis=alt.Axis(format=_axis_format(metric), tickCount=8),
                scale=alt.Scale(nice=True, padding=40)),
        tooltip=[alt.Tooltip(f"{label}:N"), alt.Tooltip(f"{value}:Q", format=_axis_format(metric))],
    )
    bars = base.mark_bar(cornerRadiusEnd=3).encode(color=color)
    # value labels just outside the bar end: right of positive bars, left of negative bars
    pos = base.transform_filter(alt.datum[value] >= 0).mark_text(align="left", dx=4, color=GREY).encode(
        text=alt.Text(f"{value}:Q", format=_axis_format(metric)))
    neg = base.transform_filter(alt.datum[value] < 0).mark_text(align="right", dx=-4, color=RED).encode(
        text=alt.Text(f"{value}:Q", format=_axis_format(metric)))
    return (bars + pos + neg).properties(height=alt.Step(30))


def line(df: pd.DataFrame, x: str, y: str, metric: str, title: str = "",
         peak_label: str | None = None) -> alt.Chart:
    data = df[[x, y]].copy()
    data[x] = data[x].astype(str)
    base = alt.Chart(data, title=title).encode(
        x=alt.X(f"{x}:N", sort=None, title=None, axis=alt.Axis(labelAngle=-45, labelOverlap="greedy")),
        y=alt.Y(f"{y}:Q", title=None, axis=alt.Axis(format=_axis_format(metric), tickCount=6)),
        tooltip=[alt.Tooltip(f"{x}:N"), alt.Tooltip(f"{y}:Q", format=_axis_format(metric))],
    )
    chart = base.mark_line(color=BLUE, point=alt.OverlayMarkDef(color=BLUE, size=30))
    if peak_label is not None:
        peak = base.transform_filter(alt.datum[x] == str(peak_label))
        chart = chart + peak.mark_point(color=ORANGE, size=120, filled=True) + \
            peak.mark_text(dy=-12, color=ORANGE).encode(text=alt.Text(f"{y}:Q", format=_axis_format(metric)))
    return chart.properties(height=320)


def forecast_line(df: pd.DataFrame, metric: str, title: str = "") -> alt.Chart:
    """df columns: month, value, kind ('Actual' / 'Forecast')."""
    data = df.copy()
    color = alt.Color("kind:N", scale=alt.Scale(domain=["Actual", "Forecast"], range=[BLUE, ORANGE]),
                      legend=alt.Legend(title=None, orient="top"))
    base = alt.Chart(data, title=title).encode(
        x=alt.X("month:N", sort=None, title=None, axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("value:Q", title=None, axis=alt.Axis(format=_axis_format(metric))),
        color=color,
        strokeDash=alt.condition(alt.datum.kind == "Forecast", alt.value([6, 4]), alt.value([1, 0])),
        tooltip=["month:N", "kind:N", alt.Tooltip("value:Q", format=_axis_format(metric))],
    )
    return base.mark_line(point=True).properties(height=320)


def scatter(df: pd.DataFrame, x: str, y: str, title: str = "") -> alt.Chart:
    data = df[[x, y]].copy()
    if len(data) > 2000:
        data = data.sample(2000, random_state=1)
    return alt.Chart(data, title=title).mark_circle(size=18, opacity=0.4, color=BLUE).encode(
        x=alt.X(f"{x}:Q"), y=alt.Y(f"{y}:Q"), tooltip=[x, y]
    ).properties(height=320)


def heatmap(df: pd.DataFrame, title: str = "") -> alt.Chart:
    """df columns: cohort, quarters_after, retention (0-1)."""
    data = df.copy()
    data["cohort"] = data["cohort"].astype(str)
    data["quarters_after"] = data["quarters_after"].astype(str)
    base = alt.Chart(data, title=title).encode(
        x=alt.X("quarters_after:O", title="Quarters after first purchase",
                sort=sorted(data["quarters_after"].unique(), key=int)),
        y=alt.Y("cohort:O", title="First purchase quarter", sort=None),
    )
    rect = base.mark_rect().encode(
        color=alt.Color("retention:Q", scale=alt.Scale(scheme="blues", domain=[0, 1]), legend=None),
        tooltip=["cohort", "quarters_after", alt.Tooltip("retention:Q", format=".0%")],
    )
    text = base.mark_text(fontSize=10).encode(
        text=alt.Text("retention:Q", format=".0%"),
        color=alt.condition(alt.datum.retention > 0.5, alt.value("white"), alt.value("black")),
    )
    return (rect + text).properties(height=alt.Step(28))
